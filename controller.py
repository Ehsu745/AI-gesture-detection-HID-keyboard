"""
controller.py（最終版）
-----------------------
獨立運作的手勢辨識系統控制器。

【按鈕行為 — GPIO17 / Pin 11】
  短按（< 3 秒）：
    第一次 → 啟動 gesture_sim.py，LED 亮
    再按一次 → 終止 gesture_sim.py，LED 滅
  長按（≥ 3 秒）：
    LED 閃爍 3 下警告 → 若辨識程式執行中先優雅關閉 → sudo shutdown -h now

【LED 行為 — GPIO27 / Pin 13】
  熄滅：閒置中（等待按鈕）
  亮起：gesture_sim.py 執行中
  閃爍 3 下：即將關機

【接線】
  按鈕：Pin 11 (GPIO17) → 按鈕 → Pin 14 (GND)
  LED ：Pin 13 (GPIO27) → 220Ω 電阻 → LED 長腳 → LED 短腳 → Pin 14 (GND)

【底層】
  gpiozero + lgpio，相容 Raspberry Pi OS Trixie 新版 gpiochip 編號
  （pinctrl-bcm2711 位於 gpiochip512，RPi.GPIO 的 add_event_detect 在此環境失效）

【前置設定】
  1. pip install gpiozero lgpio
  2. sudoers：raccoon ALL=(ALL) NOPASSWD: /sbin/shutdown
  3. systemd WorkingDirectory=/home/raccoon（lgpio 需在此建立通知檔）
"""

from gpiozero import Button, LED
import subprocess
import signal
import time

# ============================================================================
# 設定
# ============================================================================
BUTTON_PIN     = 17
LED_PIN        = 27
GESTURE_SCRIPT = "/home/raccoon/gesture_sim.py"
PYTHON_BIN     = "/home/raccoon/venv311/bin/python"
HOLD_TIME      = 3   # 長按判定時間（秒）

# ============================================================================
# GPIO 初始化
# ============================================================================
button = Button(BUTTON_PIN, pull_up=True, bounce_time=0.3, hold_time=HOLD_TIME)
led    = LED(LED_PIN)

# ============================================================================
# 狀態
# ============================================================================
process            = None   # 目前執行中的 gesture_sim.py 子程序
press_start_time   = None   # 按鈕按下時的時間戳記
long_press_handled = False  # 本次按壓是否已觸發長按（避免放開時誤觸短按）

# ============================================================================
# 輔助函式
# ============================================================================
def blink_led(times=3, on_time=0.2, off_time=0.2):
    """LED 閃爍指定次數，用於關機前警告"""
    was_lit = led.is_lit
    for _ in range(times):
        led.off()
        time.sleep(off_time)
        led.on()
        time.sleep(on_time)
    led.off()
    if was_lit:
        led.on()


def stop_gesture_process():
    """優雅終止 gesture_sim.py，超時則強制 kill"""
    global process
    if process is None:
        return
    print("[controller] 終止 gesture_sim.py")
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
    process = None
    led.off()


# ============================================================================
# 按鈕回呼
# ============================================================================
def on_pressed():
    """按下時記錄時間戳記，重置長按旗標"""
    global press_start_time, long_press_handled
    press_start_time   = time.monotonic()
    long_press_handled = False


def on_released():
    """
    放開時判斷是短按還是長按放開：
    - 長按已處理（shutdown 已觸發）→ 什麼都不做
    - 按壓時間 < HOLD_TIME → 短按，切換辨識程式狀態
    """
    global process, press_start_time

    if long_press_handled:
        return

    elapsed = (time.monotonic() - press_start_time
               if press_start_time is not None else 0)
    press_start_time = None

    if elapsed < HOLD_TIME:
        if process is None:
            # 啟動辨識程式
            print("[按鈕] 短按 → 啟動 gesture_sim.py")
            process = subprocess.Popen([PYTHON_BIN, GESTURE_SCRIPT])
            led.on()
        else:
            # 終止辨識程式
            print("[按鈕] 短按 → 終止 gesture_sim.py")
            stop_gesture_process()


def on_held():
    """
    按住達 HOLD_TIME 秒：
    LED 閃爍 3 下 → 先終止辨識程式 → 安全關機
    """
    global long_press_handled
    long_press_handled = True

    print(f"[按鈕] 長按 {HOLD_TIME} 秒 → 準備關機，LED 閃爍警告")
    blink_led(times=3)
    stop_gesture_process()

    print("[按鈕] 執行 sudo shutdown -h now")
    subprocess.run(["sudo", "shutdown", "-h", "now"])


# ============================================================================
# 註冊回呼
# ============================================================================
button.when_pressed  = on_pressed
button.when_released = on_released
button.when_held     = on_held

# ============================================================================
# 主迴圈（閒置等待，所有動作由回呼驅動）
# ============================================================================
print("Controller 啟動完成")
print(f"短按：啟動/終止辨識  |  長按 {HOLD_TIME} 秒：LED 閃爍警告後安全關機")
print("Ctrl+C 結束 controller（不會關機）")

try:
    while True:
        time.sleep(1)

except KeyboardInterrupt:
    pass

finally:
    stop_gesture_process()
    led.off()
    led.close()
    button.close()
    print("Controller 安全關閉")
