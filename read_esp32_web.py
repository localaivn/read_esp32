#!/usr/bin/env python3
"""
Dashboard web đọc dữ liệu nhiệt độ/độ ẩm từ ESP32 receiver (dht11_cc1101_receiver.ino)
qua cổng USB serial trên Orange Pi, cập nhật thời gian thực bằng SSE.

Dòng log ESP32 in ra (hỗ trợ nhiều node cùng lúc):
    Nhan OK #429 tu Node1 (ID=0xA5): 30.0C, 46.0%
    Nhan OK #430 tu Node2 (ID=0xB2): 25.7C, 55.6%

Cài đặt (1 lần):   pip3 install pyserial
Chạy:              python3 read_esp32_web.py
                   python3 read_esp32_web.py /dev/ttyACM0 115200 --http-port 8080
                   python3 read_esp32_web.py --db /duong/dan/esp32_data.db
Mở trình duyệt:    http://<ip-orange-pi>:8080

Dữ liệu được lưu vào SQLite (mặc định esp32_data.db cùng thư mục với file này),
giữ nguyên khi khởi động lại. Tải CSV:  /api/csv  (toàn bộ)  hoặc  /api/csv?days=7

Lỗi "Permission denied" trên /dev/ttyACM0:  sudo usermod -aG dialout $USER
"""

import argparse
import csv
import io
import json
import os
import queue
import re
import sqlite3
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import serial

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "esp32_data.db")
HISTORY_MAX = 2000
db = None   # kết nối SQLite, luôn truy cập trong `with lock`

LINE_PATTERN = re.compile(
    r"Nhan OK #(\d+) tu (\S+) \(ID=0x([0-9A-Fa-f]{2})\): (-?\d+(?:\.\d+)?)C, (\d+(?:\.\d+)?)%"
)

lock = threading.Lock()
history = deque(maxlen=HISTORY_MAX)   # các khung hợp lệ gần nhất (cache cho biểu đồ)
logs = deque(maxlen=100)       # các dòng log khác của ESP32
clients = []                   # hàng đợi SSE của từng trình duyệt
stats = {"frames": 0, "crc": 0, "connected": False, "port": "", "baud": 0,
         "msg": "Đang khởi động...", "started": time.time()}


def init_db(path):
    """Mở/tạo SQLite, nạp lại lịch sử gần nhất vào RAM."""
    global db
    db = sqlite3.connect(path, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("""CREATE TABLE IF NOT EXISTS frames (
        id    INTEGER PRIMARY KEY AUTOINCREMENT,
        t     REAL    NOT NULL,   -- unix time (giây)
        n     INTEGER NOT NULL,   -- số thứ tự khung từ ESP32
        node  TEXT    NOT NULL,
        dev   TEXT    NOT NULL,   -- ID hex, vd A5
        temp  REAL    NOT NULL,
        hum   REAL    NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_frames_t ON frames(t)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_frames_node_t ON frames(node, t)")
    db.commit()
    rows = db.execute(
        "SELECT t, n, node, dev, temp, hum FROM frames ORDER BY t DESC LIMIT ?",
        (HISTORY_MAX,)).fetchall()
    for t, n, node, dev, temp, hum in reversed(rows):
        history.append({"t": t, "n": n, "node": node, "id": dev, "temp": temp, "hum": hum})
    stats["frames"] = db.execute("SELECT COUNT(*) FROM frames").fetchone()[0]


def save_frame(f):
    try:
        db.execute("INSERT INTO frames (t, n, node, dev, temp, hum) VALUES (?,?,?,?,?,?)",
                   (f["t"], f["n"], f["node"], f["id"], f["temp"], f["hum"]))
        db.commit()
    except sqlite3.Error as e:
        print(f"Lỗi ghi SQLite: {e}")


def broadcast(event, data):
    payload = json.dumps({**data, "stats": stats})
    for q in list(clients):
        try:
            q.put_nowait((event, payload))
        except queue.Full:
            pass


def set_conn(ok, msg):
    with lock:
        stats["connected"] = ok
        stats["msg"] = msg
        broadcast("status", {})


def handle_line(line):
    m = LINE_PATTERN.search(line)
    with lock:
        if m:
            n, node, dev, temp, hum = m.groups()
            f = {"t": time.time(), "n": int(n), "node": node, "id": dev.upper(),
                 "temp": float(temp), "hum": float(hum)}
            history.append(f)
            save_frame(f)
            stats["frames"] += 1
            broadcast("frame", f)
        elif "Loi CRC" in line:
            stats["crc"] += 1          # nhiễu RF 433MHz bị CRC loại bỏ
            broadcast("status", {})
        else:
            entry = {"t": time.time(), "line": line}
            logs.append(entry)
            broadcast("log", entry)


def serial_worker(port, baud):
    stats["port"], stats["baud"] = port, baud
    while True:
        try:
            ser = serial.Serial(port, baud, timeout=1)
        except serial.SerialException as e:
            set_conn(False, f"Không mở được {port}: {e}")
            time.sleep(3)
            continue
        set_conn(True, f"Đã kết nối {port} @ {baud} baud")
        try:
            while True:
                raw = ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="ignore").strip()
                if line:
                    handle_line(line)
        except (serial.SerialException, OSError):
            set_conn(False, "Mất kết nối serial, đang thử lại...")
        finally:
            ser.close()
        time.sleep(3)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send_body(self, body, ctype, extra=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            self.send_body(PAGE.encode(), "text/html; charset=utf-8")
        elif url.path == "/api/csv":
            # Xuất từ SQLite (toàn bộ lịch sử); ?days=N để chỉ lấy N ngày gần nhất
            try:
                days = float(parse_qs(url.query).get("days", [0])[0])
            except ValueError:
                days = 0
            sql = "SELECT t, n, node, dev, temp, hum FROM frames"
            args = ()
            if days > 0:
                sql += " WHERE t >= ?"
                args = (time.time() - days * 86400,)
            sql += " ORDER BY t"
            with lock:
                rows = db.execute(sql, args).fetchall()
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(["time", "frame", "node", "id", "temp_c", "hum_pct"])
            for t, n, node, dev, temp, hum in rows:
                w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)),
                            n, node, "0x" + dev, temp, hum])
            self.send_body(buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8",
                           {"Content-Disposition": "attachment; filename=esp32_data.csv"})
        elif url.path == "/events":
            self.stream()
        else:
            self.send_error(404)

    def stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = queue.Queue(maxsize=500)
        with lock:
            snap = json.dumps({"history": list(history), "logs": list(logs), "stats": stats})
            clients.append(q)
        try:
            self.wfile.write(f"event: snapshot\ndata: {snap}\n\n".encode())
            self.wfile.flush()
            while True:
                try:
                    event, payload = q.get(timeout=15)
                    self.wfile.write(f"event: {event}\ndata: {payload}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            if q in clients:
                clients.remove(q)


class Server(ThreadingHTTPServer):
    daemon_threads = True


PAGE = r"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trạm thu Quan trắc môi trường qua CC1101 433 MHz</title>
<style>
:root{--bg:#08131a;--panel:#0d1c26;--line:#1b3442;--text:#cfe6ee;--dim:#6f8f9d;
--temp:#ff9d5c;--hum:#4fd1e8;--ok:#5be3a1;--warn:#ffc857;--bad:#ff5c6c;
--mono:"JetBrains Mono","IBM Plex Mono","SF Mono",ui-monospace,Menlo,Consolas,monospace}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--text);font:14px/1.5 var(--mono);padding:20px;
background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);
background-size:40px 40px;background-position:-1px -1px}
body::before{content:"";position:fixed;inset:0;background:radial-gradient(ellipse at 50% 30%,transparent 30%,var(--bg) 85%);pointer-events:none}
main{position:relative;max-width:1200px;margin:auto}
header{display:flex;flex-wrap:wrap;gap:12px;justify-content:space-between;align-items:center;margin-bottom:18px}
h1{font-size:18px;font-weight:600;letter-spacing:.02em}
h1 small{display:block;color:var(--dim);font-weight:400;font-size:12px}
.pill{display:flex;align-items:center;gap:10px;border:1px solid var(--line);background:var(--panel);padding:8px 14px;border-radius:4px}
.led{width:10px;height:10px;border-radius:50%;background:var(--bad);box-shadow:0 0 10px var(--bad)}
.led.ok{background:var(--ok);box-shadow:0 0 10px var(--ok);animation:pulse 2s infinite}
.led.warn{background:var(--warn);box-shadow:0 0 10px var(--warn)}
@keyframes pulse{50%{opacity:.4}}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:16px}
#nodes{transition:grid-template-columns .2s}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:16px;min-width:0}
.head{display:flex;justify-content:space-between;align-items:baseline;color:var(--dim);font-size:12px;margin-bottom:6px}
.big{font-size:40px;line-height:1;font-weight:300;letter-spacing:-.03em}
.big span{font-size:16px;color:var(--dim);margin-left:6px}
.t{color:var(--temp)}.h{color:var(--hum)}
.mm{display:flex;gap:14px;color:var(--dim);font-size:11px;margin:8px 0}
.mm b{color:var(--text);font-weight:500}
canvas{width:100%;height:120px;display:block}
.node-head{display:flex;align-items:baseline;gap:10px;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid var(--line)}
.node-head .name{font-size:15px;font-weight:600;letter-spacing:.02em}
.node-head .id{color:var(--dim);font-size:12px}
.node-head .age{margin-left:auto;color:var(--dim);font-size:12px;display:flex;align-items:center;gap:6px}
.node-head .dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 6px var(--ok)}
.node-panel.offline .dot{background:var(--bad);box-shadow:0 0 6px var(--bad);animation:none}
.node-panel.offline{opacity:.55}
.node-panel.offline .big b{color:var(--dim) !important}
.node-metrics{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:560px){.node-metrics{grid-template-columns:1fr}.grid{grid-template-columns:1fr !important}}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:16px;margin:16px 0}
.stat .v{font-size:22px;margin-top:2px}
.tools{display:flex;gap:6px}
button,a.btn{font:inherit;font-size:12px;color:var(--text);background:transparent;border:1px solid var(--line);padding:3px 10px;border-radius:3px;cursor:pointer;text-decoration:none}
button.on{border-color:var(--hum);color:var(--hum)}
button:focus-visible,a.btn:focus-visible{outline:2px solid var(--hum);outline-offset:2px}
#con{height:210px;overflow:auto;font-size:12px;color:var(--dim);white-space:pre-wrap}
#con .f{color:var(--text)}#con .t0{color:var(--dim)}
footer{margin-top:24px;padding:14px 0 6px;border-top:1px solid var(--line);text-align:center;color:var(--dim);font-size:12px}
footer a{color:var(--hum);text-decoration:none}
footer a:hover,footer a:focus-visible{text-decoration:underline}
@media(max-width:800px){.stats{grid-template-columns:repeat(2,1fr)}}
</style></head><body><main>
<header>
 <h1>Trạm thu Quan trắc môi trường qua CC1101 433 MHz<small id="src">—</small></h1>
 <div class="pill"><span class="led" id="led"></span><span id="state">Đang kết nối...</span></div>
</header>
<div class="panel stats">
 <div class="stat"><div class="head">Khung hợp lệ</div><div class="v" id="sf">0</div></div>
 <div class="stat"><div class="head">Node đang hoạt động</div><div class="v" id="sn">0</div></div>
 <div class="stat"><div class="head">Lỗi CRC (nhiễu RF)</div><div class="v" id="sc">0</div></div>
 <div class="stat"><div class="head">Tốc độ nhận</div><div class="v" id="sr">0/phút</div></div>
 <div class="stat"><div class="head">Nhận lần cuối</div><div class="v" id="sa">--</div></div>
</div>
<div class="grid" id="nodes"></div>
<div class="grid" style="grid-template-columns:1fr">
 <section class="panel"><div class="head"><span>Nhật ký serial</span>
  <span class="tools"><button data-w="60">1 phút</button><button data-w="600" class="on">10 phút</button><button data-w="3600">1 giờ</button><a class="btn" href="/api/csv">Tải CSV</a></span></div>
  <div id="con" role="log"></div></section>
</div>
<footer>Copyright 2026 by <a href="https://ttaisolutions.com" target="_blank" rel="noopener">TT AI Software Solutions</a></footer>
</main>
<script>
const $=id=>document.getElementById(id);
let H=[],S={},win=600,order=[];
const MAX_NODES=4,STALE_MS=20000;   // quá 20s không có khung mới -> coi là mất tín hiệu
const hhmmss=t=>new Date(t*1000).toLocaleTimeString('vi-VN',{hour12:false});
const slug=n=>n.replace(/[^a-zA-Z0-9]/g,'_');
function nodeColor(kind,idx){const hue=(kind=='temp'?24:189)+idx*33%140;return `hsl(${hue}deg 82% 62%)`}
function log(t,txt,cls){const c=$('con'),d=document.createElement('div');d.className=cls||'';
 d.textContent=`[${hhmmss(t)}] ${txt}`;c.appendChild(d);while(c.children.length>150)c.removeChild(c.firstChild);c.scrollTop=c.scrollHeight}
function frameLog(f){log(f.t,`#${f.n} từ ${f.node} (ID=0x${f.id})  ${f.temp}°C  ${f.hum}%`,'f')}

function layoutGrid(){
 const n=Math.min(order.length,MAX_NODES)||1;
 $('nodes').style.gridTemplateColumns=n===1?'1fr':n===4?'repeat(2,1fr)':`repeat(${n},1fr)`}

function ensurePanel(node){
 if(order.includes(node)||order.length>=MAX_NODES)return;
 order.push(node);layoutGrid();const s=slug(node);
 const sec=document.createElement('section');sec.className='panel node-panel';sec.id='node-'+s;
 sec.innerHTML=`
  <div class="node-head"><span class="name">${node}</span><span class="id" id="id-${s}">—</span><span class="age"><span class="dot" id="dot-${s}"></span><span id="age-${s}">—</span></span></div>
  <div class="node-metrics">
   <div><div class="head"><span>Nhiệt độ</span><span id="tm-${s}">—</span></div>
    <div class="big t"><b id="tv-${s}">--</b><span>°C</span></div>
    <div class="mm"><span>min <b id="tmin-${s}">--</b></span><span>max <b id="tmax-${s}">--</b></span><span>tb <b id="tavg-${s}">--</b></span></div>
    <canvas id="ct-${s}"></canvas></div>
   <div><div class="head"><span>Độ ẩm</span><span id="hm-${s}">—</span></div>
    <div class="big h"><b id="hv-${s}">--</b><span>%</span></div>
    <div class="mm"><span>min <b id="hmin-${s}">--</b></span><span>max <b id="hmax-${s}">--</b></span><span>tb <b id="havg-${s}">--</b></span></div>
    <canvas id="ch-${s}"></canvas></div>
  </div>`;
 $('nodes').appendChild(sec)}

function chart(cv,pts,key,color){
 const dpr=devicePixelRatio||1,w=cv.clientWidth,h=cv.clientHeight;cv.width=w*dpr;cv.height=h*dpr;
 const g=cv.getContext('2d');g.scale(dpr,dpr);g.font='11px monospace';
 const now=Date.now()/1000,t0=now-win;
 const L=34,B=18,pw=w-L-6,ph=h-B-6;
 let lo=0,hi=1;if(pts.length){lo=Math.min(...pts.map(p=>p[key]));hi=Math.max(...pts.map(p=>p[key]))}
 const mid=(lo+hi)/2,span=Math.max(hi-lo,4)/2+1;lo=Math.floor(mid-span);hi=Math.ceil(mid+span);
 const X=t=>L+(t-t0)/win*pw,Y=v=>6+ph-(v-lo)/(hi-lo)*ph;
 g.strokeStyle='#1b3442';g.fillStyle='#6f8f9d';g.lineWidth=1;g.textAlign='right';
 for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4,y=Math.round(Y(v))+.5;g.beginPath();g.moveTo(L,y);g.lineTo(L+pw,y);g.stroke();g.fillText(v.toFixed(0),L-6,y+4)}
 g.textAlign='center';
 for(let i=0;i<=4;i++){const x=Math.round(L+pw*i/4)+.5;g.beginPath();g.moveTo(x,6);g.lineTo(x,6+ph);g.stroke();
  g.fillText(i==4?'bây giờ':'-'+Math.round(win*(4-i)/4)+'s',Math.min(Math.max(x,L+16),w-22),h-4)}
 if(!pts.length){g.fillStyle='#6f8f9d';g.fillText('Chưa có tín hiệu',L+pw/2,6+ph/2);return}
 g.strokeStyle=color;g.lineWidth=1.8;g.lineJoin='round';g.beginPath();
 pts.forEach((p,i)=>{const x=X(p.t),y=Y(p[key]);i?g.lineTo(x,y):g.moveTo(x,y)});g.stroke();
 g.fillStyle=color;pts.forEach(p=>{g.fillRect(X(p.t)-1.5,Y(p[key])-1.5,3,3)});
 const p=pts[pts.length-1];g.shadowColor=color;g.shadowBlur=12;g.beginPath();g.arc(X(p.t),Y(p[key]),4.5,0,7);g.fill();g.shadowBlur=0}
function agg(pts,key){const v=pts.map(f=>f[key]);return v.length?[Math.min(...v).toFixed(1),Math.max(...v).toFixed(1),(v.reduce((a,b)=>a+b)/v.length).toFixed(1)]:['--','--','--']}

function byNode(){const m={};H.forEach(f=>{(m[f.node] ||= []).push(f)});return m}
function render(){
 const groups=byNode(),now=Date.now()/1000,t0=now-win;
 Object.keys(groups).forEach(n=>ensurePanel(n));
 order.forEach((node,idx)=>{
  const s=slug(node),all=groups[node]||[],pts=all.filter(f=>f.t>=t0),f=all[all.length-1];
  const age=f?now-f.t:Infinity,offline=age*1000>STALE_MS;
  $('node-'+s).classList.toggle('offline',offline);
  if(f){$('id-'+s).textContent=`ID 0x${f.id}`;
   $('tv-'+s).textContent=offline?'--':f.temp;$('hv-'+s).textContent=offline?'--':f.hum;
   $('tm-'+s).textContent=$('hm-'+s).textContent=hhmmss(f.t);
   $('age-'+s).textContent=(offline?'Mất tín hiệu · ':'')+(age<120?Math.round(age)+' giây trước':Math.round(age/60)+' phút trước')}
  const[tmin,tmax,tavg]=agg(all,'temp');$('tmin-'+s).textContent=tmin;$('tmax-'+s).textContent=tmax;$('tavg-'+s).textContent=tavg;
  const[hmin,hmax,havg]=agg(all,'hum');$('hmin-'+s).textContent=hmin;$('hmax-'+s).textContent=hmax;$('havg-'+s).textContent=havg;
  chart($('ct-'+s),pts,'temp',nodeColor('temp',idx));chart($('ch-'+s),pts,'hum',nodeColor('hum',idx))});
 $('sf').textContent=S.frames||0;$('sc').textContent=S.crc||0;$('sn').textContent=order.length;
 $('sr').textContent=H.filter(x=>x.t>now-60).length+'/phút';
 $('src').textContent=S.port?`${S.port} @ ${S.baud} baud · ${S.msg}`:'—'}
function tick(){
 const f=H[H.length-1],age=f?Date.now()/1000-f.t:null,led=$('led');
 $('sa').textContent=age===null?'--':age<120?Math.round(age)+' giây trước':Math.round(age/60)+' phút trước';
 if(!S.connected){led.className='led';$('state').textContent='Mất kết nối serial'}
 else if(age===null||age>30){led.className='led warn';$('state').textContent='Đã nối cổng · chờ tín hiệu'}
 else{led.className='led ok';$('state').textContent='Đang nhận tín hiệu'}}
const es=new EventSource('/events');
es.addEventListener('snapshot',e=>{const d=JSON.parse(e.data);H=d.history;S=d.stats;$('con').textContent='';
 d.logs.forEach(l=>log(l.t,l.line,'t0'));H.slice(-40).forEach(frameLog);render();tick()});
es.addEventListener('frame',e=>{const f=JSON.parse(e.data);S=f.stats;H.push(f);if(H.length>4000)H.shift();frameLog(f);render();tick()});
es.addEventListener('log',e=>{const d=JSON.parse(e.data);S=d.stats;log(d.t,d.line,'t0')});
es.addEventListener('status',e=>{S=JSON.parse(e.data).stats;render();tick()});
document.querySelectorAll('button[data-w]').forEach(b=>b.onclick=()=>{win=+b.dataset.w;
 document.querySelectorAll('button[data-w]').forEach(x=>x.classList.toggle('on',x===b));render()});
setInterval(()=>{tick();render()},1000);addEventListener('resize',render);
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description="Dashboard web cho ESP32 receiver")
    ap.add_argument("port", nargs="?", default="/dev/ttyACM0")
    ap.add_argument("baud", nargs="?", type=int, default=115200)
    ap.add_argument("--http-port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--db", default=DEFAULT_DB, help="đường dẫn file SQLite lưu lịch sử")
    a = ap.parse_args()

    init_db(a.db)
    print(f"Lưu dữ liệu: {a.db}  ({stats['frames']} khung đã có)")
    threading.Thread(target=serial_worker, args=(a.port, a.baud), daemon=True).start()
    print(f"Dashboard: http://{a.host}:{a.http_port}  (serial {a.port} @ {a.baud})  Ctrl+C để dừng")
    try:
        Server((a.host, a.http_port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng.")


if __name__ == "__main__":
    main()
