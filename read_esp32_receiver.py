#!/usr/bin/env python3
"""
Đọc dữ liệu nhiệt độ/độ ẩm từ ESP32 receiver (dht11_cc1101_receiver.ino)
qua cổng USB serial trên Orange Pi.

Dòng log ESP32 in ra có dạng:
    Nhan OK #12: ID=0xA5, 25C, 60%

Cài thư viện cần thiết (1 lần):
    pip3 install pyserial

Chạy:
    python3 read_esp32_receiver.py
    (hoặc: python3 read_esp32_receiver.py /dev/ttyACM0 115200)

Nếu bị lỗi "Permission denied" khi mở /dev/ttyACM0, thêm user vào group
dialout rồi đăng xuất/đăng nhập lại (hoặc dùng sudo chạy tạm):
    sudo usermod -aG dialout $USER
"""

import re
import sys
import time
import serial

# Cổng và tốc độ baud phải khớp với Serial.begin(115200) trong code ESP32
DEFAULT_PORT = "/dev/ttyACM0"
DEFAULT_BAUD = 115200

# Khớp với chuỗi ESP32 in ra: "Nhan OK #12: ID=0xA5, 25C, 60%"
LINE_PATTERN = re.compile(
    r"Nhan OK #(\d+): ID=0x([0-9A-Fa-f]{2}), (-?\d+)C, (\d+)%"
)


def open_serial(port: str, baud: int) -> serial.Serial:
    while True:
        try:
            ser = serial.Serial(port, baud, timeout=1)
            print(f"Da ket noi {port} @ {baud} baud")
            return ser
        except serial.SerialException as e:
            print(f"Khong mo duoc {port} ({e}), thu lai sau 3s...")
            time.sleep(3)


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PORT
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_BAUD

    ser = open_serial(port, baud)

    print("Dang lang nghe du lieu tu ESP32 receiver... (Ctrl+C de dung)")
    try:
        while True:
            try:
                raw = ser.readline()
            except serial.SerialException:
                print("Mat ket noi serial, dang thu ket noi lai...")
                ser.close()
                ser = open_serial(port, baud)
                continue

            if not raw:
                continue  # timeout, khong co du lieu moi

            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            match = LINE_PATTERN.search(line)
            if match:
                frame_no, device_id, temp, hum = match.groups()
                temp = int(temp)
                hum = int(hum)
                ts = time.strftime("%Y-%m-%d %H:%M:%S")
                print(f"[{ts}] Khung #{frame_no} (ID=0x{device_id}) "
                      f"-> Nhiet do: {temp}C, Do am: {hum}%")

                # TODO: chỗ này để lưu vào file/CSV/DB hoặc gửi lên MQTT
                # tùy nhu cầu tiếp theo của bạn.
            elif "Loi CRC" in line:
                # Nhiễu RF ngẫu nhiên trên 433MHz bị CRC loại bỏ - bình
                # thường, không cần hiện từng dòng. Bỏ comment dòng dưới
                # nếu vẫn muốn thấy để debug.
                # print(f"[log] {line}")
                pass
            else:
                # Các dòng log khác (vd "CC1101 OK.", "Bo qua goi la"...)
                print(f"[log] {line}")

    except KeyboardInterrupt:
        print("\nDa dung.")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
