import cv2
import mediapipe as mp
import serial
import time

import glob # 👈 記得在程式碼最頂端確認有沒有 import glob，沒有的話請補上

# ============================================================================
# 1. 自動模糊搜尋 Mac 系統當前的通用序列埠路徑
# ============================================================================
ports = glob.glob('/dev/cu.usbmodem*')

if not ports:
    print("❌ 錯誤：找不到任何 STM32G431 的序列埠裝置！請檢查 Hub 是否插緊。")
    exit()

# 抓取目前系統撈到的第一個符合條件的路徑
target_port = ports[0]
print(f"📡 系統動態偵測成功！自動掛載通用序列埠路徑：{target_port}")

try:
    ser = serial.Serial(target_port, 115200, timeout=1)
    print("成功連接到 STM32G431！")
except Exception as e:
    print(f"串口連接失敗：{e}")
    exit()

# ============================================================================
# 2. 初始化 MediaPipe 手勢偵測
# ============================================================================
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
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
# 4. 主迴圈
# ============================================================================
cap = cv2.VideoCapture(0)
print("AI 手勢辨識系統啟動！請對著相機比「讚」或「倒讚」...")

try:
    while cap.isOpened():
        success, frame = cap.read()
        if not success:
            print("無法讀取視訊鏡頭，停止。")
            break  # FIX: 原本是 continue，鏡頭真的斷掉會無限迴圈

        frame = cv2.flip(frame, 1)
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = hands.process(rgb_frame)

        current_cmd = 0x00

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)
                current_cmd = detect_gesture(hand_landmarks)

                # 顯示辨識結果
                if current_cmd == 0x01:
                    cv2.putText(frame, "THUMB UP (NEXT)",
                                (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                elif current_cmd == 0x02:
                    cv2.putText(frame, "THUMB DOWN (PREV)",
                                (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                else:
                    cv2.putText(frame, "...",
                                (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2)

        # ====================================================================
        # 5. 邊緣觸發：手勢改變才發送
        # ====================================================================
        if current_cmd != last_cmd and current_cmd != 0:
            send_packet(current_cmd)

        last_cmd = current_cmd  # FIX: 移到外層，手離開時重置為 0，
                                #      下次比同一手勢仍可觸發

        cv2.imshow('AI Gesture Simulator', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except KeyboardInterrupt:
    pass

# ============================================================================
# 6. 釋放資源
# ============================================================================
cap.release()
cv2.destroyAllWindows()
ser.close()
print("系統安全關閉。")
