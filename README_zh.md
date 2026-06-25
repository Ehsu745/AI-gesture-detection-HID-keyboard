# AI 手勢偵測控制系統

> 🌐 語言：[English](./README.md) | **繁體中文**

透過即時影像辨識手勢，將辨識結果轉換為標準 USB HID 鍵盤訊號，實現免接觸式簡報控制。

---

## 系統架構

![系統架構圖](./images/HW.png)

```
USB 鏡頭 (1080P, UVC)
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

| 元件 | 角色 | 主要技術 |
|---|---|---|
| USB 鏡頭 | 影像擷取 | UVC 標準，免驅動 |
| Raspberry Pi 4 | 手勢辨識與封包編碼 | Python 3.11 + MediaPipe Hands + OpenCV |
| XIAO ESP32-S3 | 封包解析與 HID 輸出 | Arduino + TinyUSB |
| Computer | 指令接收端 | 標準 HID 鍵盤驅動（系統原生） |

---

## 通訊協議

![軟體架構圖](./images/SW.png)

樹莓派與 XIAO 之間採用自定義 4-byte 封包，搭配 checksum 防止資料毀損：

| Byte | 內容 | 說明 |
|---|---|---|
| 0 | `0x5A` | Header，固定值，用於封包同步 |
| 1 | `cmd` | `0x01` = 下一頁／`0x02` = 上一頁 |
| 2 | `0x00` | Reserved，保留供未來擴充 |
| 3 | `checksum` | `(byte0 + byte1 + byte2) & 0xFF` |

接收端逐位元組讀取，狀態機比對 Header 完成封包同步，並驗證 checksum 後才執行對應動作。

---

## 手勢辨識邏輯

使用 MediaPipe Hands 取得 21 個手部關鍵點座標，透過雙重條件判斷降低誤觸發率：

1. **四指彎曲判定**：食指、中指、無名指、小指的指尖 y 座標皆大於其 PIP 關節 y 座標（Y 軸向下為正）
2. **拇指方向判定**：拇指尖端 y 座標相對於掌心中心點（食指根部與小指根部中點）的相對位置，決定朝上（讚）或朝下（倒讚）

僅當「四指彎曲」且「拇指方向明確」同時成立時，才回報有效手勢，避免一般張掌動作被誤判。

採用邊緣觸發送出：手勢狀態改變且非 0 時才送出封包，避免重複觸發。

---

## 獨立運作模式（controller.py）

`controller.py` 使整套手勢辨識系統可在無需 SSH 連線、無需螢幕或鍵盤的情況下獨立運作，透過 systemd service 開機自動啟動，全程以實體按鈕操作。

### 按鈕行為

| 操作 | 行為 |
|---|---|
| 短按（< 3 秒） | 第一次按下啟動 `gesture_sim.py`，LED 亮；再按一次終止辨識，LED 滅 |
| 長按（≥ 3 秒） | LED 快速閃爍 3 下作為警告，接著執行安全關機 |

### 事件驅動設計

`controller.py` 採用 `gpiozero` 函式庫（底層使用 `lgpio`），透過 `Button.when_pressed`、`Button.when_released`、`Button.when_held` 回呼監聽按鈕事件，CPU 在無事件時保持閒置，不進行輪詢（polling）。

> ⚠️ 原始設計使用 `RPi.GPIO.add_event_detect()`，但 Raspberry Pi OS Trixie 的新版核心將 BCM GPIO controller 重新編號為 `gpiochip512`，導致 `RuntimeError: Failed to add edge detection`。改用 `gpiozero` + `lgpio` 可正確對應新編號。

長短按的判定：按下時（`when_pressed`）記錄時間戳記，放開時（`when_released`）計算時間差，若 < 3 秒視為短按；若按壓達 3 秒門檻，則由 `when_held` 回呼觸發關機流程。

### 子程序生命週期管理

- **啟動**：`subprocess.Popen()` 建立 `gesture_sim.py` 子程序，獨立於 controller 主程式運作，LED 亮起
- **終止**：發送 `SIGINT`，使 `gesture_sim.py` 進入 `except KeyboardInterrupt` 區塊正常釋放攝影機與序列埠資源；若 3 秒內未結束則強制 `kill()`，LED 熄滅

### 開機自動啟動（systemd）

`gesture-controller.service` 設定為開機自動啟動。`WorkingDirectory=/home/raccoon` 為必要設定——若省略，`lgpio` 無法在根目錄建立通知檔案，會 fallback 回 `RPi.GPIO` 並再次觸發上述錯誤。

```ini
[Service]
User=raccoon
WorkingDirectory=/home/raccoon
ExecStart=/home/raccoon/venv311/bin/python /home/raccoon/controller.py
Restart=on-failure
RestartSec=3
```

---

## 硬體接線

### 樹莓派 ↔ XIAO ESP32-S3

| 樹莓派 | XIAO ESP32-S3 |
|---|---|
| Pin 8 (GPIO14 / TX) | D7 (GPIO44 / RX) |
| Pin 9 (GND) | GND |

### 樹莓派 ↔ 按鈕／LED

| GPIO | 實體 Pin | 功能 | 接法 |
|---|---|---|---|
| GPIO17 | Pin 11 | 短按啟動/終止・長按關機 | GPIO17 → 按鈕 → GND（內部 Pull-up） |
| GPIO27 | Pin 13 | 狀態 LED | GPIO27 → 220Ω 電阻 → LED 長腳 → LED 短腳 → GND |
| GND | Pin 14 | 共用接地 | 按鈕與 LED 的 GND 端共用 |

---

## 環境設定

### Raspberry Pi

Trixie 預設的 Python 3.13 與 MediaPipe 不相容，需透過 pyenv 安裝 Python 3.11.9：

```bash
curl https://pyenv.run | bash
pyenv install 3.11.9
pyenv local 3.11.9

python -m venv venv311
source venv311/bin/activate
pip install mediapipe==0.10.8 opencv-python pyserial RPi.GPIO gpiozero lgpio
```

執行 `sudo raspi-config` → Interface Options → Serial Port，啟用硬體 UART（login shell over serial: **No**，serial port hardware: **Yes**）。

UART 裝置路徑為 `/dev/ttyS0`（**非** `/dev/ttyAMA0`），鮑率 115200。

> `gesture_sim.py` 為**無頭模式（headless）**版本，已移除 `cv2.imshow()` 等需要顯示環境的程式碼，可直接由 `controller.py` 在背景啟動，不需要 SSH 或顯示器。

### XIAO ESP32-S3

使用 `arduino-cli` + `Makefile`（不使用 Arduino IDE GUI）：

```bash
# 安裝 ESP32 開發板套件
arduino-cli config add board_manager.additional_urls \
    https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32

# 編譯並燒錄
make flash

# 序列埠監控
make monitor
```

`USB.h`、`USBHIDKeyboard.h` 屬於 `esp32:esp32` 核心內建函式庫，安裝核心後即可直接使用，無需另外下載。

> ⚠️ 設定 `ARDUINO_USB_MODE=0`（USB-OTG / HID 模式）後，序列埠（用於上傳）會消失。重新燒錄前須：按住 **BOOT** → 插入 USB → 放開 BOOT。若裝置完全無法被偵測，可先嘗試改接 USB Hub。

---

## 執行方式

### 手動執行（除錯用）

```bash
ssh raccoon@rocketraccoon.local
source venv311/bin/activate
python gesture_sim.py
```

### 獨立運作模式（systemd 自動啟動）

開機後 `gesture-controller.service` 自動啟動，無需 SSH 或任何手動操作。

```bash
# 查看 service 狀態
sudo systemctl status gesture-controller.service

# 即時查看 log
journalctl -u gesture-controller.service -f
```

開機後建議等待約 30-60 秒（讓 USB 鏡頭驅動完全初始化）再按按鈕。

---

## 系統規格摘要

| 項目 | 數值 |
|---|---|
| 辨識手勢 | 👍 下一頁 / 👎 上一頁 |
| 通訊鮑率 | 115200 bps |
| 封包長度 | 4 bytes（含 checksum） |
| 影像解析度 | 1080P @ 30fps |
| 硬體總成本 | 約 NT$3,615 |

---

## 部署補充

### sudoers（長按關機所需）

```bash
sudo visudo -f /etc/sudoers.d/raccoon-shutdown
# 加入：
raccoon ALL=(ALL) NOPASSWD: /sbin/shutdown
```

### systemd service 啟用

```bash
sudo systemctl daemon-reload
sudo systemctl enable gesture-controller.service
sudo systemctl start gesture-controller.service
```

---

## 授權聲明

本專案目前作為課程期末作業之學術成果展示，尚未附加正式的開源授權條款。硬體外殼設計基於 [Olvin 的 Raspberry Pi 4 Case](https://www.thingiverse.com/thing:4882960)，採用 **CC BY** 授權。
