import cv2
import mediapipe as mp
import serial
import time

# ============================================================================
# 1. 序列埠設定（Raspberry Pi GPIO UART）
# ============================================================================
SERIAL_PORT = '/dev/ttyS0'
BAUD_RATE = 115200

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    print(f"成功連接到 XIAO ESP32-S3！序列埠：{SERIAL_PORT}")
except Exception as e:
    print(f"串口連接失敗：{e}")
    exit()

# ============================================================================
# 2. 初始化 MediaPipe 手勢偵測
# ============================================================================
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7
)

last_cmd = 0

# ============================================================================
# 3. 輔助函式
# ============================================================================
def is_finger_folded(landmarks, tip_idx, pip_idx):
    """指尖 Y 座標大於第二關節 = 手指彎曲（Y 軸向下為正）"""
    return landmarks[tip_idx].y > landmarks[pip_idx].y

def detect_gesture(hand_landmarks):
    """
    回傳手勢指令：
      0x01 = 大拇指朝上（讚）
      0x02 = 大拇指朝下（倒讚）
      0x00 = 無法辨識
    條件：食指、中指、無名指、小指必須全部彎曲，
          才確認是「純拇指」手勢，避免誤觸發。
    """
    lm = hand_landmarks.landmark

    # 確認四指彎曲（tip vs PIP 關節）
    fingers_folded = all([
        is_finger_folded(lm, 8,  6),   # 食指
        is_finger_folded(lm, 12, 10),  # 中指
        is_finger_folded(lm, 16, 14),  # 無名指
        is_finger_folded(lm, 20, 18),  # 小指
    ])

    if not fingers_folded:
        return 0x00

    thumb_tip = lm[4]
    thumb_ip  = lm[3]
    palm_center_y = (lm[9].y + lm[17].y) / 2

    if thumb_tip.y < palm_center_y and thumb_tip.y < thumb_ip.y:
        return 0x01  # 讚

    if thumb_tip.y > palm_center_y and thumb_tip.y > thumb_ip.y:
        return 0x02  # 倒讚

    return 0x00

def send_packet(cmd):
    """組封包並發送"""
    checksum = (0x5A + cmd + 0x00) & 0xFF
    packet = bytes([0x5A, cmd, 0x00, checksum])
    ser.write(packet)
    print(f"手勢變更！發送封包: {[hex(b) for b in packet]}")

# ============================================================================
# 4. 主迴圈（無頭模式：不開視窗、不等待按鍵）
# ============================================================================
cap = cv2.VideoCapture(0)
print("AI 手勢辨識系統啟動！請對著相機比「讚」或「倒讚」...")

try:
    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            print("無法讀取視訊鏡頭，停止。")
            break  # 鏡頭真的斷掉會直接結束，避免無限迴圈

        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb_frame)

        current_cmd = 0x00

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                current_cmd = detect_gesture(hand_landmarks)

        # ====================================================================
        # 5. 邊緣觸發：手勢改變才發送
        # ====================================================================
        if current_cmd != last_cmd and current_cmd != 0:
            send_packet(current_cmd)

        last_cmd = current_cmd  # 手離開時重置為 0，下次比同一手勢仍可觸發

except KeyboardInterrupt:
    pass

# ============================================================================
# 6. 釋放資源
# ============================================================================
cap.release()
ser.close()
print("系統安全關閉。")
