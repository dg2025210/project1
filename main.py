from machine import Pin, ADC
from neopixel import NeoPixel
import network
import socket
import time
import random
import _thread
import wifi_config as cfg

# ============================================
# WS2813 Mini 전용 타이밍
# ============================================
TIMING = (280, 515, 515, 745)
led = NeoPixel(Pin(cfg.LED_PIN), cfg.NUM_LEDS, timing=TIMING)
mq2 = ADC(Pin(cfg.MQ2_PIN))

# ============================================
# 10칸 색상
# ============================================
SLOT_COLORS = [
    (255, 50, 50),    # 0: 빨강
    (255, 140, 0),    # 1: 주황
    (255, 230, 0),    # 2: 노랑
    (150, 255, 0),    # 3: 연두
    (0, 220, 0),      # 4: 초록
    (0, 230, 180),    # 5: 민트
    (0, 180, 255),    # 6: 하늘
    (60, 80, 255),    # 7: 파랑
    (170, 80, 255),   # 8: 보라
    (255, 60, 200),   # 9: 핑크
]

penalties = [
    "노래 한 곡 부르기!",
    "30초 댄스 타임!",
    "개인기 보여주기",
    "음료수 사오기",
    "웃긴 셀카 10장 찍기",
    "닭다리 춤 추기",
    "친구에게 사랑한다 전화",
    "다음 게임 상품 사기",
    "1분간 말하지 않기",
    "팔굽혀펴기 10개"
]

state = {
    'spinning': False,
    'current_pos': 0,
    'last_winner': -1,
    'gas_value': 0,
    'sensor_diff': 0,
    'spin_count': 0,
    'spin_trigger': False,
    'spin_power': 0.5,
}

lock = _thread.allocate_lock()

# ============================================
# LED 헬퍼
# ============================================
def clear():
    for i in range(cfg.NUM_LEDS):
        led[i] = (0, 0, 0)
    led.write()

def show_idle():
    for i in range(cfg.NUM_LEDS):
        c = SLOT_COLORS[i]
        led[i] = (c[0] // 12, c[1] // 12, c[2] // 12)
    led.write()

def show_pointer(position):
    for i in range(cfg.NUM_LEDS):
        c = SLOT_COLORS[i]
        if i == position:
            led[i] = c
        else:
            led[i] = (c[0] // 18, c[1] // 18, c[2] // 18)
    led.write()

def hsv_to_rgb(h, s, v):
    c = v * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = v - c
    if h < 60: r, g, b = c, x, 0
    elif h < 120: r, g, b = x, c, 0
    elif h < 180: r, g, b = 0, c, x
    elif h < 240: r, g, b = 0, x, c
    elif h < 300: r, g, b = x, 0, c
    else: r, g, b = c, 0, x
    return (int((r+m)*255), int((g+m)*255), int((b+m)*255))

def winner_celebration(slot):
    c = SLOT_COLORS[slot]
    for _ in range(5):
        clear()
        time.sleep(0.12)
        led[slot] = c
        led.write()
        time.sleep(0.12)
    for cycle in range(25):
        for i in range(cfg.NUM_LEDS):
            hue = (i * 36 + cycle * 30) % 360
            led[i] = hsv_to_rgb(hue, 1.0, 1.0)
        led.write()
        time.sleep(0.05)
    for i in range(cfg.NUM_LEDS):
        led[i] = c
    led.write()

# ============================================
# WiFi 연결
# ============================================
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print("WiFi 연결 중...")
        print("SSID:", cfg.WIFI_SSID)
        wlan.connect(cfg.WIFI_SSID, cfg.WIFI_PASSWORD)
        
        for i in range(40):
            if wlan.isconnected():
                break
            pos = i % cfg.NUM_LEDS
            for j in range(cfg.NUM_LEDS):
                led[j] = (0, 50, 100) if j == pos else (0, 5, 15)
            led.write()
            time.sleep(0.5)
        
        if not wlan.isconnected():
            print("WiFi 연결 실패!")
            return None
    
    ip = wlan.ifconfig()[0]
    print("=" * 45)
    print("WiFi 연결 성공!")
    print("IP:", ip)
    print("접속:  http://" + ip)
    print("=" * 45)
    
    for i in range(cfg.NUM_LEDS):
        led[i] = (0, 50, 0)
    led.write()
    time.sleep(0.8)
    clear()
    
    return ip

# ============================================
# HTML 페이지 생성 (분리된 방식)
# ============================================
def generate_main_page():
    # 색상과 벌칙을 JS 배열 문자열로
    colors_js = "[" + ",".join(["[%d,%d,%d]" % (c[0], c[1], c[2]) for c in SLOT_COLORS]) + "]"
    
    # 벌칙 문자열 (특수문자 이스케이프)
    penalty_items = []
    for p in penalties:
        p_safe = p.replace('"', '\\"').replace("'", "\\'")
        penalty_items.append('"' + p_safe + '"')
    penalties_js = "[" + ",".join(penalty_items) + "]"
    
    # 벌칙 입력 폼
    rows = ""
    for i in range(cfg.NUM_LEDS):
        c = SLOT_COLORS[i]
        hex_color = "#%02x%02x%02x" % (c[0], c[1], c[2])
        rows += '<div class="slot" style="border-left: 6px solid ' + hex_color + ';">'
        rows += '<label>' + str(i+1) + '번 칸</label>'
        rows += '<input type="text" name="p' + str(i) + '" value="' + penalties[i] + '" maxlength="50">'
        rows += '</div>'
    
    # ===== CSS =====
    css = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Apple SD Gothic Neo', sans-serif;
    background: radial-gradient(circle at center, #2d1b4e, #0f0524);
    color: white;
    padding: 15px;
    min-height: 100vh;
}
h1 {
    text-align: center;
    font-size: 28px;
    text-shadow: 0 0 20px #ff00ff;
    margin-bottom: 5px;
}
.subtitle {
    text-align: center;
    color: #aaa;
    font-size: 12px;
    margin-bottom: 20px;
}
.roulette-container {
    position: relative;
    width: 320px;
    height: 320px;
    margin: 20px auto;
}
.roulette-wheel {
    width: 100%;
    height: 100%;
    border-radius: 50%;
    transition: transform 4s cubic-bezier(0.17, 0.67, 0.21, 1);
    box-shadow: 0 0 40px rgba(255,0,255,0.5);
}
.roulette-wheel svg {
    width: 100%;
    height: 100%;
    display: block;
}
.pointer {
    position: absolute;
    top: -15px;
    left: 50%;
    transform: translateX(-50%);
    width: 0;
    height: 0;
    border-left: 20px solid transparent;
    border-right: 20px solid transparent;
    border-top: 35px solid #ffd700;
    filter: drop-shadow(0 0 10px rgba(255,215,0,0.8));
    z-index: 10;
}
.center-circle {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 60px;
    height: 60px;
    background: radial-gradient(circle, #fff, #ffd700);
    border-radius: 50%;
    box-shadow: 0 0 20px #ffd700;
    z-index: 5;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 28px;
}
.start-btn {
    display: block;
    width: 90%;
    max-width: 350px;
    margin: 20px auto;
    padding: 20px;
    font-size: 22px;
    font-weight: bold;
    background: linear-gradient(45deg, #ff006e, #ff8a00, #ffce00);
    color: white;
    border: none;
    border-radius: 50px;
    cursor: pointer;
    box-shadow: 0 5px 25px rgba(255,0,110,0.5);
}
.start-btn:active { transform: scale(0.95); }
.start-btn:disabled {
    background: #555;
    opacity: 0.5;
}
.winner-box {
    background: linear-gradient(135deg, #ff6b6b, #feca57);
    padding: 25px;
    border-radius: 20px;
    text-align: center;
    margin: 20px auto;
    max-width: 400px;
    font-size: 18px;
    font-weight: bold;
    color: #333;
    line-height: 1.6;
    min-height: 80px;
}
.winner-box.waiting {
    background: rgba(255,255,255,0.1);
    color: #aaa;
}
.winner-box.spinning {
    background: linear-gradient(45deg, #00f5ff, #ff00ff);
    color: white;
}
.status-bar {
    max-width: 400px;
    margin: 15px auto;
    padding: 12px 18px;
    background: rgba(0,0,0,0.4);
    border-radius: 12px;
}
.status-row {
    display: flex;
    justify-content: space-between;
    font-size: 13px;
    margin: 4px 0;
}
.status-label { color: #888; }
.status-value { color: #00ffff; font-weight: bold; }
.gas-meter {
    height: 8px;
    background: rgba(255,255,255,0.1);
    border-radius: 4px;
    overflow: hidden;
    margin-top: 8px;
}
.gas-fill {
    height: 100%;
    background: linear-gradient(90deg, #00ff00, #ffff00, #ff0000);
    width: 0%;
    transition: width 0.2s;
}
.penalties-section {
    max-width: 400px;
    margin: 30px auto 0;
}
h2 {
    font-size: 18px;
    color: #ffd700;
    margin-bottom: 10px;
    text-align: center;
}
.slot {
    background: rgba(255,255,255,0.06);
    padding: 10px 12px;
    margin: 8px 0;
    border-radius: 8px;
}
.slot label {
    display: block;
    font-weight: bold;
    margin-bottom: 4px;
    color: #ffd700;
    font-size: 12px;
}
.slot input {
    width: 100%;
    padding: 8px;
    font-size: 14px;
    border: none;
    border-radius: 5px;
}
.save-btn {
    width: 100%;
    padding: 14px;
    font-size: 16px;
    font-weight: bold;
    background: linear-gradient(45deg, #667eea, #764ba2);
    color: white;
    border: none;
    border-radius: 10px;
    margin-top: 12px;
}
.hint {
    text-align: center;
    color: #888;
    font-size: 12px;
    margin: 15px 0;
}
</style>
"""
    
    # ===== HTML 본문 =====
    body_html = """
<h1>🎰 운명의 룰렛 🎰</h1>
<p class="subtitle">LIVE | MQ-2 + WS2813</p>

<div class="roulette-container">
    <div class="pointer"></div>
    <div class="roulette-wheel" id="wheel">
        <svg viewBox="-100 -100 200 200" id="wheelSvg"></svg>
    </div>
    <div class="center-circle">🎯</div>
</div>

<div class="winner-box waiting" id="winnerBox">
    👻 START 버튼을 누르거나<br>입김을 불어보세요!
</div>

<button class="start-btn" id="startBtn" onclick="triggerSpin()">
    🎰 룰렛 돌리기!
</button>

<div class="status-bar">
    <div class="status-row">
        <span class="status-label">상태:</span>
        <span class="status-value" id="status">대기 중</span>
    </div>
    <div class="status-row">
        <span class="status-label">총 횟수:</span>
        <span class="status-value" id="spinCount">0</span>
    </div>
    <div class="status-row">
        <span class="status-label">💨 입김 강도:</span>
        <span class="status-value" id="diffValue">0</span>
    </div>
    <div class="gas-meter">
        <div class="gas-fill" id="gasFill"></div>
    </div>
</div>

<p class="hint">💡 입김이 셀수록 룰렛이 더 많이 돌아가요!</p>

<div class="penalties-section">
    <h2>📝 벌칙 설정</h2>
    <form action="/save" method="POST">
""" + rows + """
        <button type="submit" class="save-btn">💾 저장하기</button>
    </form>
</div>
"""
    
    # ===== JavaScript (별도 문자열, f-string 안 씀!) =====
    js_code = """
<script>
var colors = __COLORS__;
var penalties = __PENALTIES__;
var NUM_SLOTS = 10;

// 룰렛 SVG 그리기
var svg = document.getElementById('wheelSvg');
var sliceAngle = 360 / NUM_SLOTS;

for (var i = 0; i < NUM_SLOTS; i++) {
    var startAngle = (i * sliceAngle - 90 - sliceAngle/2) * Math.PI / 180;
    var endAngle = ((i+1) * sliceAngle - 90 - sliceAngle/2) * Math.PI / 180;
    
    var x1 = Math.cos(startAngle) * 95;
    var y1 = Math.sin(startAngle) * 95;
    var x2 = Math.cos(endAngle) * 95;
    var y2 = Math.sin(endAngle) * 95;
    
    var c = colors[i];
    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    var d = 'M 0 0 L ' + x1 + ' ' + y1 + ' A 95 95 0 0 1 ' + x2 + ' ' + y2 + ' Z';
    path.setAttribute('d', d);
    path.setAttribute('fill', 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')');
    path.setAttribute('stroke', '#fff');
    path.setAttribute('stroke-width', '1');
    svg.appendChild(path);
    
    var midAngle = (i * sliceAngle - 90) * Math.PI / 180;
    var tx = Math.cos(midAngle) * 65;
    var ty = Math.sin(midAngle) * 65;
    var text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    text.setAttribute('x', tx);
    text.setAttribute('y', ty);
    text.setAttribute('text-anchor', 'middle');
    text.setAttribute('dominant-baseline', 'middle');
    text.setAttribute('fill', 'white');
    text.setAttribute('font-size', '20');
    text.setAttribute('font-weight', 'bold');
    text.textContent = (i + 1);
    svg.appendChild(text);
}

var wheel = document.getElementById('wheel');
var currentRotation = 0;
var isSpinning = false;
var lastWinnerShown = -1;
var fastSpinInterval = null;

function spinWheelToPosition(targetPos, duration) {
    var targetAngle = -(targetPos * 36);
    var extraRotations = 5;
    var currentMod = currentRotation % 360;
    var diff = targetAngle - currentMod;
    var finalRotation = currentRotation + (extraRotations * 360) + diff;
    
    wheel.style.transition = 'transform ' + duration + 's cubic-bezier(0.17, 0.67, 0.21, 1)';
    wheel.style.transform = 'rotate(' + finalRotation + 'deg)';
    currentRotation = finalRotation;
}

function triggerSpin() {
    if (isSpinning) return;
    fetch('/spin');
}

function updateStatus() {
    fetch('/status').then(function(res) {
        return res.json();
    }).then(function(data) {
        document.getElementById('status').textContent = 
            data.spinning ? '🎰 회전 중!' : '⏸️ 대기 중';
        document.getElementById('spinCount').textContent = data.spin_count;
        document.getElementById('diffValue').textContent = data.sensor_diff;
        
        var pct = Math.min(100, (data.sensor_diff / 30000) * 100);
        document.getElementById('gasFill').style.width = pct + '%';
        
        document.getElementById('startBtn').disabled = data.spinning;
        
        // 회전 시작
        if (data.spinning && !isSpinning) {
            isSpinning = true;
            lastWinnerShown = -1;
            
            document.getElementById('winnerBox').className = 'winner-box spinning';
            document.getElementById('winnerBox').innerHTML = '🎰 회전 중...<br>두근두근...';
            
            wheel.style.transition = 'transform 0.1s linear';
            fastSpinInterval = setInterval(function() {
                currentRotation += 60;
                wheel.style.transform = 'rotate(' + currentRotation + 'deg)';
            }, 50);
        }
        
        // 회전 종료
        if (!data.spinning && isSpinning && data.last_winner >= 0) {
            isSpinning = false;
            
            if (fastSpinInterval) {
                clearInterval(fastSpinInterval);
                fastSpinInterval = null;
            }
            
            spinWheelToPosition(data.last_winner, 3);
            
            setTimeout(function() {
                if (lastWinnerShown !== data.last_winner) {
                    document.getElementById('winnerBox').className = 'winner-box';
                    document.getElementById('winnerBox').innerHTML = 
                        '🎉 ' + (data.last_winner + 1) + '번 당첨! 🎉<br>📜 ' + 
                        penalties[data.last_winner];
                    lastWinnerShown = data.last_winner;
                }
            }, 3000);
        }
    }).catch(function(e) {
        console.error(e);
    });
}

setInterval(updateStatus, 300);
updateStatus();
</script>
"""
    
    # JS 코드에 색상/벌칙 데이터 삽입
    js_code = js_code.replace("__COLORS__", colors_js)
    js_code = js_code.replace("__PENALTIES__", penalties_js)
    
    # 최종 HTML 조립
    html = "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    html += "<meta name='viewport' content='width=device-width, initial-scale=1.0'>"
    html += "<title>운명의 룰렛</title>"
    html += css
    html += "</head><body>"
    html += body_html
    html += js_code
    html += "</body></html>"
    
    return html

# ============================================
# URL 디코딩
# ============================================
def url_decode(s):
    result = bytearray()
    i = 0
    while i < len(s):
        if s[i] == '%':
            try:
                result.append(int(s[i+1:i+3], 16))
                i += 3
            except:
                i += 1
        elif s[i] == '+':
            result.append(0x20)
            i += 1
        else:
            result.append(ord(s[i]))
            i += 1
    try:
        return result.decode('utf-8')
    except:
        return result.decode('utf-8', 'ignore')

def parse_post(body):
    data = {}
    for pair in body.split('&'):
        if '=' in pair:
            key, value = pair.split('=', 1)
            data[key] = url_decode(value)
    return data

# ============================================
# 웹 서버 (Core 1)
# ============================================
def web_server_thread():
    global penalties
    
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(3)
    print("웹 서버 시작!")
    
    while True:
        try:
            cl, addr = s.accept()
            cl.settimeout(3.0)
            request = cl.recv(2048).decode('utf-8')
            first_line = request.split('\r\n')[0]
            
            if 'GET /status' in first_line:
                with lock:
                    json_data = '{'
                    json_data += '"spinning":' + ('true' if state["spinning"] else 'false') + ','
                    json_data += '"current_pos":' + str(state["current_pos"]) + ','
                    json_data += '"last_winner":' + str(state["last_winner"]) + ','
                    json_data += '"sensor_diff":' + str(state["sensor_diff"]) + ','
                    json_data += '"spin_count":' + str(state["spin_count"])
                    json_data += '}'
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n')
                cl.send(json_data)
            
            elif 'GET /spin' in first_line:
                with lock:
                    if not state['spinning']:
                        state['spin_trigger'] = True
                        state['spin_power'] = 0.7
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nOK')
            
            elif 'POST /save' in first_line:
                if '\r\n\r\n' in request:
                    body = request.split('\r\n\r\n', 1)[1]
                    data = parse_post(body)
                    for i in range(cfg.NUM_LEDS):
                        key = 'p' + str(i)
                        if key in data and data[key].strip():
                            penalties[i] = data[key].strip()
                    print("벌칙 업데이트!")
                cl.send('HTTP/1.0 303 See Other\r\nLocation: /\r\n\r\n')
            
            else:
                html = generate_main_page()
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n')
                # 큰 HTML을 나눠서 전송
                chunk_size = 1024
                for i in range(0, len(html), chunk_size):
                    cl.send(html[i:i+chunk_size])
            
            cl.close()
        except Exception as e:
            print("웹 에러:", e)
            try:
                cl.close()
            except:
                pass

# ============================================
# 룰렛 실행
# ============================================
def spin_roulette(power):
    print("룰렛 회전! 파워:", power)
    
    with lock:
        state['spinning'] = True
        state['spin_count'] += 1
    
    total_steps = int(25 + power * 70)
    position = random.randint(0, cfg.NUM_LEDS - 1)
    
    for step in range(total_steps):
        position = (position + 1) % cfg.NUM_LEDS
        show_pointer(position)
        with lock:
            state['current_pos'] = position
        
        progress = step / total_steps
        delay = 0.04 + (progress ** 2.5) * 0.5
        time.sleep(delay)
    
    with lock:
        state['last_winner'] = position
    
    print("당첨!", position + 1, "번")
    print("벌칙:", penalties[position])
    
    winner_celebration(position)
    show_pointer(position)
    
    with lock:
        state['spinning'] = False

# ============================================
# 센서 캘리브레이션
# ============================================
def calibrate():
    print("MQ-2 센서 예열 중...")
    samples = []
    for i in range(20):
        samples.append(mq2.read_u16())
        for j in range(cfg.NUM_LEDS):
            hue = (i * 18 + j * 36) % 360
            led[j] = hsv_to_rgb(hue, 1.0, 0.3)
        led.write()
        time.sleep(0.3)
    baseline = sum(samples) // len(samples)
    print("베이스라인:", baseline)
    return baseline

# ============================================
# 메인
# ============================================
def main():
    print("\n=== 운명의 룰렛 시작 ===\n")
    
    ip = connect_wifi()
    if not ip:
        return
    
    _thread.start_new_thread(web_server_thread, ())
    time.sleep(1)
    
    baseline = calibrate()
    show_idle()
    
    print("입김을 불거나 웹 버튼을 누르세요!")
    print("URL: http://" + ip)
    
    while True:
        gas_value = mq2.read_u16()
        diff = gas_value - baseline
        
        with lock:
            state['gas_value'] = gas_value
            state['sensor_diff'] = max(0, diff)
            web_trigger = state['spin_trigger']
            web_power = state['spin_power']
            is_spinning = state['spinning']
        
        if web_trigger and not is_spinning:
            with lock:
                state['spin_trigger'] = False
            spin_roulette(web_power)
            time.sleep(cfg.COOLDOWN_TIME)
        
        elif diff > cfg.TRIGGER_THRESHOLD and not is_spinning:
            print("입김 감지! 변화량:", diff)
            
            max_diff = diff
            for _ in range(20):
                v = mq2.read_u16() - baseline
                if v > max_diff:
                    max_diff = v
                with lock:
                    state['sensor_diff'] = max(0, v)
                time.sleep(0.05)
            
            power = min(max_diff / 30000, 1.0)
            spin_roulette(power)
            time.sleep(cfg.COOLDOWN_TIME)
        
        time.sleep(0.05)

try:
    main()
except KeyboardInterrupt:
    clear()
    print("\n종료!")
except Exception as e:
    clear()
    print("오류:", e)
    import sys
    sys.print_exception(e)
