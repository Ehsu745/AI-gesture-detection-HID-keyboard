# AI 手勢偵測控制系統

透過即時影像辨識手勢，將辨識結果轉換為標準 USB HID 鍵盤訊號，實現免接觸式簡報控制。

---

## 系統架構

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

樹莓派端提供 `controller.py`，使整套手勢辨識系統可在無需 SSH 連線的情況下獨立運作。

### 設計概念：邊緣觸發中斷（Edge-Triggered Interrupt）

與輪詢（polling）不同，本控制器透過 `RPi.GPIO.add_event_detect()` 註冊 GPIO 中斷，CPU 在無事件時保持閒置，僅在按鈕觸發 falling edge 時才執行對應的中斷服務常式（ISR）。

```python
GPIO.add_event_detect(BUTTON_PIN, GPIO.FALLING,
                       callback=button_isr, bouncetime=300)
```

| 設計要素 | 說明 |
|---|---|
| **觸發方式** | Falling edge（按鈕按下時電位由 HIGH → LOW） |
| **Debounce** | `bouncetime=300`（毫秒），過濾機械按鈕物理彈跳造成的多次觸發 |
| **ISR 行為** | 切換子程序（`gesture_sim.py`）的啟動／終止狀態 |
| **狀態指示** | LED 點亮表示辨識程式執行中，熄滅表示閒置 |

### 子程序生命週期管理

- **啟動**：`subprocess.Popen()` 建立 `gesture_sim.py` 子程序，獨立於 controller 主程式運作
- **終止**：發送 `SIGINT`（等同 `Ctrl+C`），使 `gesture_sim.py` 進入既有的 `except KeyboardInterrupt` 區塊，正常釋放攝影機與序列埠資源；若 3 秒內未結束則強制 `kill()`

---

## 硬體接線

### 樹莓派 ↔ XIAO ESP32-S3

| 樹莓派 | XIAO ESP32-S3 |
|---|---|
| Pin 8 (GPIO14 / TX) | D7 (GPIO44 / RX) |
| Pin 9 (GND) | GND |

### 樹莓派 ↔ 按鈕／LED

| GPIO | 功能 | 接法 |
|---|---|---|
| GPIO17 | 啟動／終止按鈕 | GPIO17 → 按鈕 → GND（內部 Pull-up） |
| GPIO27 | 狀態 LED | GPIO27 → 220Ω 電阻 → LED → GND |

---

## 環境設定

### Raspberry Pi

```bash
# Python 3.11（MediaPipe 相容版本，透過 pyenv 安裝）
python -m venv venv311
source venv311/bin/activate
pip install mediapipe opencv-python pyserial RPi.GPIO

# 啟用 GPIO UART
sudo raspi-config  # Interface Options → Serial Port
#   - login shell over serial: No
#   - serial port hardware: Yes
```

UART 裝置位於 `/dev/ttyS0`，鮑率 115200。

### XIAO ESP32-S3

使用 Arduino + `arduino-cli`，需指定 USB-OTG 模式以啟用 HID：

```bash
arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 \
    --build-property "build.extra_flags=-DARDUINO_USB_MODE=0 -DARDUINO_USB_CDC_ON_BOOT=0" \
    main
```

> ⚠️ 進入 USB-OTG（HID）模式後，序列埠（用於上傳）將消失。重新上傳須進入 Bootloader 模式：按住 **BOOT** 不放 → 插入 USB → 放開 BOOT。

---

## 執行方式

### 手動執行（除錯用）

```bash
ssh raccoon@rocketraccoon.local
source venv311/bin/activate
python gesture_sim.py
```

### 獨立運作模式

```bash
python controller.py
```

按下按鈕啟動辨識（LED 亮），再按一次終止（LED 滅）。

---

## 系統規格摘要

| 項目 | 數值 |
|---|---|
| 辨識手勢 | 👍 下一頁 / 👎 上一頁 |
| 通訊鮑率 | 115200 bps |
| 封包長度 | 4 bytes（含 checksum） |
| 影像解析度 | 1080P @ 30fps |
| 硬體總成本 | 約 NT$3,615 |
