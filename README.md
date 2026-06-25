# AI Gesture Detection Control System

> 🌐 Language: **English** | [繁體中文](./README_zh.md)

Control presentations with hand gestures — no remote, no wearable, no contact required.

---

## System Architecture

![System Architecture](./images/HW.png)

```
USB Camera (1080P, UVC)
    │  USB
    ▼
Raspberry Pi 4 (MediaPipe Hands)
    │  UART, 115200 baud, 4-byte packet
    ▼
XIAO ESP32-S3 (TinyUSB HID Keyboard)
    │  USB HID
    ▼
Computer (PowerPoint / Keynote / Slides)
```

| Component | Role | Technology |
|---|---|---|
| USB Camera | Image capture | UVC standard, driverless |
| Raspberry Pi 4 | Gesture inference & packet encoding | Python 3.11 + MediaPipe Hands + OpenCV |
| XIAO ESP32-S3 | Packet parsing & HID output | Arduino + TinyUSB |
| Computer | Command receiver | Native HID keyboard driver |

---

## Communication Protocol

![Software Architecture](./images/SW.png)

A custom 4-byte packet with checksum is used between the Raspberry Pi and XIAO:

| Byte | Content | Description |
|---|---|---|
| 0 | `0x5A` | Header — fixed value for packet sync |
| 1 | `cmd` | `0x01` = Next page / `0x02` = Previous page |
| 2 | `0x00` | Reserved for future use |
| 3 | `checksum` | `(byte0 + byte1 + byte2) & 0xFF` |

The receiver reads byte-by-byte, syncs on the header, then validates the checksum before executing any action.

---

## Gesture Recognition Logic

Uses MediaPipe Hands to obtain 21 hand landmarks. A dual-condition approach minimises false triggers:

1. **Four-finger curl check**: Index, middle, ring, and pinky fingertip y-coordinates all exceed their respective PIP joint y-coordinates (y-axis points downward)
2. **Thumb direction check**: Thumb tip y-coordinate relative to palm centre (midpoint of index and pinky knuckles) determines up (👍) or down (👎)

A gesture is only reported when **both conditions** are satisfied simultaneously, preventing open-palm movements from being misidentified.

Edge-triggered send: a packet is only transmitted when the detected gesture **changes** and is non-zero, preventing repeated firing.

---

## Standalone Mode (controller.py)

`controller.py` enables the system to run without any SSH connection, screen, or keyboard. It is auto-started at boot via systemd and controlled entirely through a physical button.

### Button Behaviour

| Action | Result |
|---|---|
| Short press (< 3 s) | First press: start `gesture_sim.py`, LED on. Second press: stop recognition, LED off. |
| Long press (≥ 3 s) | LED flashes 3 times as warning, then system shuts down safely. |

### Event-Driven Design

`controller.py` uses `gpiozero` (backed by `lgpio`) with `Button.when_pressed`, `Button.when_released`, and `Button.when_held` callbacks. The CPU remains idle between events — no polling.

> ⚠️ The original design used `RPi.GPIO.add_event_detect()`, but Raspberry Pi OS Trixie remaps the BCM GPIO controller to `gpiochip512`, causing `RuntimeError: Failed to add edge detection`. Switching to `gpiozero` + `lgpio` resolves this.

Short vs long press is determined by recording a timestamp on press (`when_pressed`) and computing elapsed time on release (`when_released`). If ≥ 3 s, the long-press shutdown handler takes over instead.

### Subprocess Lifecycle

- **Start**: `subprocess.Popen()` launches `gesture_sim.py` as an independent subprocess; LED turns on.
- **Stop**: `SIGINT` is sent to `gesture_sim.py`, triggering its `except KeyboardInterrupt` block to cleanly release the camera and serial port. If it does not exit within 3 s, `kill()` is called. LED turns off.

### Boot Auto-Start (systemd)

`gesture-controller.service` is enabled at boot. The key requirement is `WorkingDirectory=/home/raccoon` — without it, `lgpio` cannot create its notification socket under `/` and falls back to `RPi.GPIO`, re-triggering the error above.

```ini
[Service]
User=raccoon
WorkingDirectory=/home/raccoon
ExecStart=/home/raccoon/venv311/bin/python /home/raccoon/controller.py
Restart=on-failure
RestartSec=3
```

---

## Hardware Wiring

### Raspberry Pi ↔ XIAO ESP32-S3

| Raspberry Pi | XIAO ESP32-S3 |
|---|---|
| Pin 8 (GPIO14 / TX) | D7 (GPIO44 / RX) |
| Pin 9 (GND) | GND |

### Raspberry Pi ↔ Button / LED

| GPIO | Physical Pin | Function | Wiring |
|---|---|---|---|
| GPIO17 | Pin 11 | Short press: start/stop · Long press: shutdown | GPIO17 → button → GND (internal pull-up) |
| GPIO27 | Pin 13 | Status LED | GPIO27 → 220 Ω resistor → LED anode → LED cathode → GND |
| GND | Pin 14 | Shared ground | Shared by button and LED |

---

## Environment Setup

### Raspberry Pi

Trixie ships with Python 3.13, which is incompatible with MediaPipe. Install Python 3.11.9 via pyenv:

```bash
curl https://pyenv.run | bash
pyenv install 3.11.9
pyenv local 3.11.9

python -m venv venv311
source venv311/bin/activate
pip install mediapipe==0.10.8 opencv-python pyserial RPi.GPIO gpiozero lgpio
```

Enable GPIO UART via `sudo raspi-config` → Interface Options → Serial Port:
- login shell over serial: **No**
- serial port hardware: **Yes**

UART device: `/dev/ttyS0` (not `/dev/ttyAMA0`), baud rate 115200.

> `gesture_sim.py` runs in **headless mode** (no display required). It is designed to be launched by `controller.py` in the background without SSH or a monitor.

### XIAO ESP32-S3

Using `arduino-cli` + `Makefile` (no Arduino IDE GUI):

```bash
# Install ESP32 board package
arduino-cli config add board_manager.additional_urls \
    https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32

# Compile and flash
make flash

# Serial monitor
make monitor
```

`USB.h` and `USBHIDKeyboard.h` are bundled with the `esp32:esp32` core — no separate installation needed.

> ⚠️ After flashing with `ARDUINO_USB_MODE=0` (USB-OTG / HID mode), the serial upload port disappears. To re-flash: hold **BOOT** → plug in USB → release **BOOT**. If the device is not detected at all, try connecting through a USB hub first.

---

## Running the System

### Manual (debug)

```bash
ssh raccoon@rocketraccoon.local
source venv311/bin/activate
python gesture_sim.py
```

### Standalone mode (systemd auto-start)

After boot, `gesture-controller.service` starts automatically. No SSH needed.

```bash
# Check service status
sudo systemctl status gesture-controller.service

# Live log
journalctl -u gesture-controller.service -f
```

Wait ~30–60 s after power-on for the USB camera driver to initialise before pressing the button.

---

## System Specifications

| Item | Value |
|---|---|
| Supported gestures | 👍 Next page / 👎 Previous page |
| UART baud rate | 115200 bps |
| Packet length | 4 bytes (incl. checksum) |
| Camera resolution | 1080P @ 30 fps |
| Hardware cost | ~NT$3,615 |

---

## Deployment (Flash Procedure)

### sudoers (required for long-press shutdown)

```bash
sudo visudo -f /etc/sudoers.d/raccoon-shutdown
# Add:
raccoon ALL=(ALL) NOPASSWD: /sbin/shutdown
```

### systemd service

```bash
sudo systemctl daemon-reload
sudo systemctl enable gesture-controller.service
sudo systemctl start gesture-controller.service
```

---

## License

This project is an academic coursework submission. No open-source license has been applied at this stage. The 3D enclosure design is based on [Olvin's Raspberry Pi 4 Case](https://www.thingiverse.com/thing:4882960), licensed under **CC BY**.
