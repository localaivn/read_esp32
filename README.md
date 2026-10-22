# read_esp32

Dashboard web Python để thu thập dữ liệu nhiệt độ, độ ẩm từ ESP32 receiver, hiển thị theo thời gian thực và lưu vào SQLite.

## Mục tiêu

Script `read_esp32_web.py` đọc dữ liệu từ cổng serial `/dev/ttyACM0` (hoặc cổng tùy chọn), parse chuỗi log do ESP32 gửi lên, và hiển thị các giá trị theo từng node trên giao diện web.

Dữ liệu gồm:
- Nhiệt độ (°C)
- Độ ẩm (%)
- Tên node
- Device ID (hex, ví dụ `0xA5`)
- Thời gian nhận
- Số khung, lỗi CRC, trạng thái kết nối

Những chuỗi log hợp lệ có dạng như:

```text
Nhan OK #429 tu Node1 (ID=0xA5): 30.0C, 46.0%
Nhan OK #430 tu Node2 (ID=0xB2): 25.7C, 55.6%
```

## Tính năng chính

- Kết nối serial với ESP32 receiver qua USB/UART
- Parse nhiều node cùng lúc
- Hiển thị dashboard web realtime bằng Server-Sent Events (SSE)
- Lưu lịch sử vào SQLite (`esp32_data.db`)
- Tải dữ liệu ra CSV qua endpoint `/api/csv`
- Hỗ trợ hiển thị trạng thái kết nối, lỗi CRC, log serial, biểu đồ theo thời gian
- Dễ chạy trên Orange Pi / Raspberry Pi / Linux server

## Yêu cầu hệ thống

- Python 3.8+
- `pyserial`
- Truy cập vào cổng serial `/dev/ttyACM0` hoặc cổng tương ứng
- Nếu dùng Linux, người chạy phải có quyền truy cập vào nhóm `dialout`

### Cài đặt Python và thư viện

```bash
sudo apt update
sudo apt install -y python3 python3-pip
pip3 install pyserial
```

Nếu gặp lỗi quyền truy cập serial:

```bash
sudo usermod -aG dialout $USER
```

Sau đó logout/login hoặc reboot để nhóm mới có hiệu lực.

## Cấu trúc repo

```text
read_esp32/
├── README.md
├── read_esp32_web.py
├── read_esp32_receiver.py
├── esp32_data.db
├── read_esp32.service
└── ...
```

- `read_esp32_web.py`: server web + parser dữ liệu từ ESP32
- `read_esp32_receiver.py`: script liên quan đến receiver ESP32 (nếu có trong repo)
- `esp32_data.db`: database SQLite lưu dữ liệu lịch sử
- `read_esp32.service`: service systemd để bật tự động lúc máy khởi động

## Chạy script thủ công

### Chạy mặc định

```bash
python3 read_esp32_web.py
```

Mặc định script sẽ:
- mở `/dev/ttyACM0`
- baudrate `115200`
- chạy server web trên `0.0.0.0:8080`
- lưu DB vào `esp32_data.db` ở cùng thư mục với file script

### Chạy với cổng và baud tùy chọn

```bash
python3 read_esp32_web.py /dev/ttyUSB0 9600 --http-port 8080
```

### Chạy với DB riêng

```bash
python3 read_esp32_web.py --db /opt/esp32/esp32_data.db
```

### Mở dashboard

Mở trình duyệt:

```text
http://<ip-cua-may>:8080
```

Ví dụ:

```text
http://192.168.1.50:8080
```

## Endpoint và API

### 1) Dashboard chính

```text
/
```

Trang web hiển thị biểu đồ, node, log, trạng thái kết nối.

### 2) Sự kiện realtime

```text
/events
```

Dùng Server-Sent Events để push cập nhật về:
- snapshot dữ liệu ban đầu
- frame mới
- log serial
- trạng thái kết nối

### 3) Tải dữ liệu CSV

```text
/api/csv
```

Lấy toàn bộ dữ liệu từ SQLite.

```text
/api/csv?days=7
```

Lấy dữ liệu trong 7 ngày gần nhất.

## Lưu dữ liệu

Script lưu dữ liệu vào SQLite với bảng `frames` có các trường:
- `id`
- `t` (timestamp Unix)
- `n` (số frame)
- `node`
- `dev`
- `temp`
- `hum`

Các bảng và index được tạo tự động nếu chưa tồn tại.

## Hướng dẫn cài đặt service systemd (khởi động cùng máy)

File service đã có trong repo: `read_esp32.service`.

### 1) Sao chép file service vào `/etc/systemd/system/`

```bash
sudo cp read_esp32.service /etc/systemd/system/
```

### 2) Chỉnh sửa nếu cần

Mở file và thay đổi thông tin người dùng / đường dẫn nếu máy bạn khác với ví dụ.

```bash
sudo nano /etc/systemd/system/read_esp32.service
```

Ví dụ nội dung chuẩn:

```ini
[Unit]
Description=ESP32 Environment Monitor Dashboard
After=network.target

[Service]
Type=simple
User=localaivn
WorkingDirectory=/home/localaivn/read_esp32
ExecStart=/usr/bin/python3 /home/localaivn/read_esp32/read_esp32_web.py --host 0.0.0.0 --http-port 8080 --db /home/localaivn/read_esp32/esp32_data.db
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### 3) Reload systemd

```bash
sudo systemctl daemon-reload
```

### 4) Bật service

```bash
sudo systemctl enable read_esp32.service
sudo systemctl start read_esp32.service
```

### 5) Kiểm tra trạng thái

```bash
sudo systemctl status read_esp32.service
```

### 6) Xem log

```bash
sudo journalctl -u read_esp32.service -f
```

### 7) Dừng hoặc khởi động lại service

```bash
sudo systemctl stop read_esp32.service
sudo systemctl restart read_esp32.service
```

## Khắc phục sự cố

### Lỗi `Permission denied` khi mở serial port

```bash
sudo usermod -aG dialout $USER
```

Sau đó đăng xuất và đăng nhập lại.

### Không nhận dữ liệu từ ESP32

- Kiểm tra cổng serial (`/dev/ttyACM0`, `/dev/ttyUSB0`)
- Kiểm tra baudrate (`115200` theo mặc định)
- Kiểm tra dây nối và module RF/433 MHz
- Kiểm tra log bằng:

```bash
sudo journalctl -u read_esp32.service -f
```

### Script không chạy trên máy khởi động

```bash
sudo systemctl daemon-reload
sudo systemctl restart read_esp32.service
sudo systemctl status read_esp32.service
```

## Lưu ý quan trọng

- Script hoạt động tốt khi ESP32 receiver gửi dữ liệu đúng định dạng `Nhan OK ...`
- Nếu có nhiễu RF, các frame lỗi CRC sẽ được bỏ qua và tăng biến `crc`
- Dữ liệu được lưu liên tục nên không mất khi khởi động lại máy

## Ví dụ truy cập dữ liệu

```bash
curl http://localhost:8080/api/csv?days=1 -o esp32_1day.csv
```

## Tác giả

Dự án này được phát triển để thu thập dữ liệu môi trường từ ESP32 qua giao tiếp RF 433 MHz và hiển thị trên dashboard web.

## License

Dùng theo quy định của repo hiện tại.

---

Nếu bạn muốn, tôi có thể tiếp tục giúp bạn:
1. Tạo thêm file `install.sh` để cài đặt tự động
2. Tạo file `docker-compose.yml` để chạy bằng Docker
3. Tạo script `check_esp32.sh` để tự động restart khi mất kết nối serial
4. Điều chỉnh service để chạy với user khác hoặc port khác
