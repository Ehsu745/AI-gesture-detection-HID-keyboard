#include "USB.h"
#include "USBHIDKeyboard.h"
USBHIDKeyboard Keyboard;
// 封包狀態機
uint8_t packet[4];
uint8_t packet_idx = 0;
void setup() {
    Serial.begin(115200);  // 接樹莓派/Mac 的 UART
    Keyboard.begin();
    USB.begin();
}
void loop() {
    while (Serial.available()) {
        uint8_t b = Serial.read();
        if (packet_idx == 0) {
            if (b == 0x5A) packet[packet_idx++] = b;
        } else if (packet_idx < 3) {
            packet[packet_idx++] = b;
        } else {
            packet[3] = b;
            uint8_t chk = (packet[0] + packet[1] + packet[2]) & 0xFF;
            if (chk == packet[3]) {
                if (packet[1] == 0x01) {
                    Keyboard.press(KEY_RIGHT_ARROW); // 下一頁
                    delay(100);
                    Keyboard.release(KEY_RIGHT_ARROW);
                } else if (packet[1] == 0x02) {
                    Keyboard.press(KEY_LEFT_ARROW);  // 上一頁
                    delay(100);
                    Keyboard.release(KEY_LEFT_ARROW);
                }
            }
            packet_idx = 0;
        }
    }
}
