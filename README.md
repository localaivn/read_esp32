# read_esp32

Dashboard Python để đọc dữ liệu nhiệt độ và độ ẩm từ ESP32 receiver qua cổng serial, hiển thị trên web theo thời gian thực và lưu vào SQLite.

## Mục tiêu

`read_esp32_web.py` đang chạy trên máy Linux/Orange Pi, mở cổng serial để đọc các dòng log từ ESP32 receiver, parse dữ liệu cảm biến và hiển thị trên giao diện web.

Dữ liệu thu thập được bao gồm:
- Tên node
- Device ID (hex như `0xA5`)
- Nhiệt độ (°C)
- Độ ẩm (%)
- Số khung truyền
- Thời gian nhận
- Trạng thái kết nối và lỗi CRC

Chuỗi dữ liệu hợp lệ có dạng:

```text
Nhan OK #429 tu Node1 (ID=0xA5): 30.0C, 46.0%
Nhan OK #430 tu Node2 (ID=0xB2): 25.7C, 55.6%
```

## Tính năng chính

- Kết nối serial với ESP32 receiver
- Hỗ trợ nhiều node cùng lúc
- Giao diện web realtime bằng Server-Sent Events (SSE)
- Lưu lịch sử vào SQLite (`esp32_data.db`)
- Xuất dữ liệu ra CSV để tải về
- Hiển thị log serial, trạng thái kết nối, lỗi CRC, biểu đồ nhiệt độ/độ ẩm
- Chạy được trên Orange Pi, Raspberry Pi, Linux server

## Yêu cầu hệ thống

- Python 3.8+
- `pyserial`
- Quyền truy cập cổng serial, ví dụ `/dev/ttyACM0` hoặc `/dev/ttyUSB0`
- Nếu dùng Ubuntu/Debian, cần thêm user vào nhóm `dialout`

### Cài đặt thư viện

```bash
sudo apt update
sudo apt install -y python3 python3-pip
pip3 install pyserial
```

Nếu gặp lỗi quyền truy cập serial:

```bash
sudo usermod -aG dialout $USER
```

Sau đó đăng xuất / đăng nhập lại hoặc khởi động lại máy.

## Thư mục dự án

```text
/home/orangepi/read_esp32/
├── README.md
├── read_esp32_web.py
├── read_esp32_receiver.py
├── esp32_data.db
├── read_esp32.service
└── ...
```

- `read_esp32_web.py`: script chính chạy dashboard web và đọc serial
- `read_esp32_receiver.py`: script liên quan đến ESP32 receiver
- `esp32_data.db`: file database SQLite lưu dữ liệu
- `read_esp32.service`: service systemd để tự chạy khi khởi động

## Chạy script thủ công

### Chạy mặc định

```bash
cd /home/orangepi/read_esp32
python3 read_esp32_web.py
```

Mặc định script sẽ:
- mở `/dev/ttyACM0`
- chạy ở baudrate `115200`
- server web lắng nghe trên `0.0.0.0:8080`
- lưu dữ liệu vào `/home/orangepi/read_esp32/esp32_data.db`

### Chạy với cổng serial khác

```bash
cd /home/orangepi/read_esp32
python3 read_esp32_web.py /dev/ttyUSB0 9600 --http-port 8080
```

### Chạy với DB khác

```bash
cd /home/orangepi/read_esp32
python3 read_esp32_web.py --db /home/orangepi/read_esp32/esp32_data.db
```

### Mở dashboard

Mở trình duyệt:

```text
http://<ip-cua-orange-pi>:8080
```

Ví dụ:

```text
http://192.168.1.20:8080
```

## Endpoint API

### 1) Dashboard chính

```text
/
```

### 2) Sự kiện realtime

```text
/events
```

Dùng SSE để cập nhật dữ liệu mới, log và trạng thái mạng/kết nối.

### 3) Tải dữ liệu CSV

```text
/api/csv
```

Tải toàn bộ dữ liệu.

```text
/api/csv?days=7
```

Tải dữ liệu trong 7 ngày gần nhất.

## Cấu trúc dữ liệu SQLite

Script tạo bảng `frames` nếu chưa có, với các cột:
- `id`
- `t` (timestamp Unix)
- `n` (số frame)
- `node`
- `dev`
- `temp`
- `hum`

Dữ liệu được lưu liên tục nên không mất khi restart.

## Cài đặt service systemd để chạy khi khởi động

File service đã được tạo tại repo này: `/home/orangepi/read_esp32/read_esp32.service`

### 1) Copy file service vào /etc/systemd/system

```bash
sudo cp /home/orangepi/read_esp32/read_esp32.service /etc/systemd/system/
```

### 2) Reload systemd

```bash
sudo systemctl daemon-reload
```

### 3) Bật service

```bash
sudo systemctl enable read_esp32.service
sudo systemctl start read_esp32.service
```

### 4) Kiểm tra trạng thái

```bash
sudo systemctl status read_esp32.service
```

### 5) Xem log chạy service

```bash
sudo journalctl -u read_esp32.service -f
```

### 6) Dừng / restart service

```bash
sudo systemctl stop read_esp32.service
sudo systemctl restart read_esp32.service
```

## Nội dung file service

```ini
[Unit]
Description=Read ESP32 Web Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=orangepi
WorkingDirectory=/home/orangepi/read_esp32
ExecStart=/usr/bin/python3 /home/orangepi/read_esp32/read_esp32_web.py --host 0.0.0.0 --http-port 8080 --db /home/orangepi/read_esp32/esp32_data.db
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

## Khắc phục sự cố

### Lỗi `Permission denied` trên cổng serial

```bash
sudo usermod -aG dialout $USER
```

Sau đó logout/login hoặc reboot.

### Không nhận dữ liệu từ ESP32

- Kiểm tra cổng serial có đúng không: `/dev/ttyACM0` hoặc `/dev/ttyUSB0`
- Kiểm tra baudrate: `115200`
- Kiểm tra kết nối RF 433 MHz
- Kiểm tra log service:

```bash
sudo journalctl -u read_esp32.service -f
```

### Service không chạy khi máy khởi động

```bash
sudo systemctl daemon-reload
sudo systemctl restart read_esp32.service
sudo systemctl status read_esp32.service
```

## Lưu ý quan trọng

- Script chỉ parse đúng khi ESP32 gửi chuỗi theo định dạng chuẩn `Nhan OK ...`
- Nếu có nhiễu RF, các frame CRC lỗi sẽ bị loại bỏ
- Dữ liệu được lưu vào SQLite và giữ nguyên khi máy khởi động lại

## Ví dụ tải dữ liệu về máy

```bash
curl http://localhost:8080/api/csv?days=1 -o esp32_1day.csv
```

---

Nếu bạn muốn, tôi có thể tiếp tục giúp với các bước sau:
1. Tạo script `install_read_esp32.sh` để cài đặt tự động
2. Tạo file `check_service.sh` để tự hồi phục khi mất kết nối serial
3. Sửa service để chạy ở port 80 / 443 hoặc với user khác
