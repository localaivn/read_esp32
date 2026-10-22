# KIOSH.md

# Chromium kiosk cho dashboard ESP32

Hướng dẫn này dùng Chromium mở `http://127.0.0.1:8080` ở chế độ kiosk khi máy khởi động.

## 1) Cài đặt Chromium trên Orange Pi

### Cài đặt gói cơ bản

```bash
sudo apt update
sudo apt install -y chromium x11-xserver-utils unclutter fonts-liberation xdg-utils
```

Nếu hệ thống báo không tìm thấy gói `chromium`, thử:

```bash
sudo apt install -y chromium-browser
```

Nếu package vẫn không có, kiểm tra:

```bash
apt-cache search chromium | head
```

### Cài đặt nếu cần

```bash
sudo apt install -y mesa-utils
```

## 2) Tạo file kiosk.sh

File đã có sẵn trong repo:

```bash
/home/orangepi/read_esp32/kiosk.sh
```

Nội dung chuẩn:

```bash
#!/bin/bash

export DISPLAY=:0
export XAUTHORITY=/home/orangepi/.Xauthority

xset -dpms || true
xset s off || true
xset s noblank || true

unclutter -idle 0 >/dev/null 2>&1 &

xrandr --output HDMI-1 --auto >/dev/null 2>&1 || true

while true; do
  chromium \
    --kiosk \
    --disable-dev-shm-usage \
    --no-sandbox \
    --private-window \
    http://127.0.0.1:8080

  echo "Chromium exited. Restarting in 2 seconds..."
  sleep 2
done
```

Cho quyền thực thi:

```bash
chmod +x /home/orangepi/read_esp32/kiosk.sh
```

## 3) Cách 1: Chạy bằng systemd service (khuyến nghị nhất)

File service đã có trong repo:

```bash
/home/orangepi/read_esp32/kiosk.service
```

Cài đặt:

```bash
sudo cp /home/orangepi/read_esp32/kiosk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable kiosk.service
sudo systemctl start kiosk.service
sudo systemctl status kiosk.service
```

Nếu cần xem log:

```bash
sudo journalctl -u kiosk.service -f
```

## 4) Cách 2: Chạy bằng desktop autostart

Nếu máy đang chạy desktop (LXDE/Xfce/Mate), tạo file:

```bash
mkdir -p /home/orangepi/.config/autostart
nano /home/orangepi/.config/autostart/kiosk.desktop
```

Nội dung:

```ini
[Desktop Entry]
Type=Application
Name=Kiosk
Exec=/bin/bash /home/orangepi/read_esp32/kiosk.sh
X-GNOME-Autostart-enabled=true
```

Lưu file và logout/login lại.

## 5) Cách 3: Chạy bằng rc.local (có thể dùng nhưng không phải cách tốt nhất)

Tạo file:

```bash
sudo nano /etc/rc.local
```

Thêm trước dòng `exit 0`:

```bash
export DISPLAY=:0
export XAUTHORITY=/home/orangepi/.Xauthority
su - orangepi -c '/bin/bash /home/orangepi/read_esp32/kiosk.sh' &
```

Cho quyền thực thi:

```bash
sudo chmod +x /etc/rc.local
```

Và khởi động lại máy.

## 6) Quan trọng khi chạy Chromium trên Orange Pi

- Dùng `--no-sandbox` khi chạy như root hoặc khi hệ thống báo sandbox
- Dùng `--disable-dev-shm-usage` để tránh lỗi bộ nhớ/SHM
- Đảm bảo `DISPLAY=:0` và `XAUTHORITY` đúng
- Nếu hệ thống không có desktop, dùng `systemd` + `graphical.target`
- Nếu màn hình không hiện gì, kiểm tra: `echo $DISPLAY`, `ls -l /tmp/.X11-unix`

## 7) Kiểm tra nhanh

```bash
systemctl is-enabled kiosk.service
systemctl status kiosk.service
journalctl -u kiosk.service -n 50 --no-pager
```

## 8) Khởi động lại và kiểm tra

```bash
sudo systemctl restart kiosk.service
sudo systemctl status kiosk.service
```

Mở trình duyệt tới:

```text
http://127.0.0.1:8080
```

## 9) Khắc phục thường gặp

### Chromium không khởi động

```bash
chromium --version
```

Nếu lỗi thiếu paket, cài lại:

```bash
sudo apt install --reinstall chromium
```

### Không có màn hình

```bash
echo $DISPLAY
ls -l /tmp/.X11-unix
```

### Không thấy tab hoặc lỗi sandbox

```bash
chromium --kiosk --no-sandbox --disable-dev-shm-usage http://127.0.0.1:8080
```

## 10) Gợi ý tốt nhất

Nếu máy Orange Pi đang chạy nền không có desktop, nên dùng:

- `read_esp32.service`
- `kiosk.service`

Và để browser chạy ở `DISPLAY=:0` sau khi X11 đã chạy. Đây là cách ổn định nhất.
