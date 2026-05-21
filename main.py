from machine import Pin, ADC
from neopixel import NeoPixel
import network
import socket
import time
import random
import math
import _thread
import wifi_config as cfg

# WS2813 Mini 타이밍 ⚠️ 중요!
TIMING = (280, 515, 515, 745)
led = NeoPixel(Pin(cfg.LED_PIN), cfg.NUM_LEDS, timing=TIMING)
mq2 = ADC(Pin(cfg.MQ2_PIN))

# 10칸 색상
SLOT_COLORS = [
    (255, 50, 50),    (255, 140, 0),    (255, 230, 0),    (150, 255, 0),
    (0, 220, 0),      (0, 230, 180),    (0, 180, 255),    (60, 80, 255),
    (170, 80, 255),   (255, 60, 200),
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

# 게임 상태
GAME_IDLE = 0
GAME_BLOWING = 1
GAME_SPINNING = 2
GAME_RESULT = 3

state = {
    'game_state': GAME_IDLE,
    'current_pos': 0,
    'last_winner': -1,
    'sensor_diff': 0,
    'spin_count': 0,
    'start_trigger': False,
    'blow_remaining': 5,
    'max_blow': 0,
    'baseline': 0,
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

def show_countdown(power_level):
    num_lit = int(cfg.NUM_LEDS * power_level)
    for i in range(cfg.NUM_LEDS):
        if i < num_lit:
            if power_level < 0.33:
                led[i] = (0, 200, 0)
            elif power_level < 0.66:
                led[i] = (200, 200, 0)
            else:
                led[i] = (255, 50, 0)
        else:
            led[i] = (5, 5, 20)
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
    print("브라우저에서 접속:  http://" + ip)
    print("=" * 45)
    for i in range(cfg.NUM_LEDS):
        led[i] = (0, 50, 0)
    led.write()
    time.sleep(0.8)
    clear()
    return ip

# ============================================
# HTML 페이지 생성
# ============================================
def generate_main_page():
    rows = ""
    for i in range(cfg.NUM_LEDS):
        c = SLOT_COLORS[i]
        hex_color = "#%02x%02x%02x" % (c[0], c[1], c[2])
        rows += '<div class="slot" style="border-left: 6px solid ' + hex_color + ';">'
        rows += '<label>' + str(i+1) + '번 칸</label>'
        rows += '<input type="text" name="p' + str(i) + '" value="' + penalties[i] + '" maxlength="50">'
        rows += '</div>'
    
    colors_js = "[" + ",".join(["[%d,%d,%d]" % (c[0], c[1], c[2]) for c in SLOT_COLORS]) + "]"
    
    penalty_items = []
    for p in penalties:
        p_safe = p.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
        penalty_items.append('"' + p_safe + '"')
    penalties_js = "[" + ",".join(penalty_items) + "]"
    
    css = '''
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, sans-serif;
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
    margin-bottom: 15px;
}
.status-top {
    text-align: center;
    font-size: 16px;
    color: #ffd700;
    font-weight: bold;
    margin-bottom: 15px;
    padding: 10px;
    background: rgba(0,0,0,0.3);
    border-radius: 10px;
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
    box-shadow: 0 0 40px rgba(255,0,255,0.5);
    transition: transform 4s cubic-bezier(0.17, 0.67, 0.21, 1);
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
    width: 110px;
    height: 110px;
    background: radial-gradient(circle, #fff, #ffd700);
    border-radius: 50%;
    box-shadow: 0 0 20px #ffd700;
    z-index: 5;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    font-weight: bold;
    color: #333;
    cursor: pointer;
    text-align: center;
    user-select: none;
    -webkit-tap-highlight-color: transparent;
}
.center-circle:hover {
    box-shadow: 0 0 40px #ffd700;
}
.center-circle:active {
    transform: translate(-50%, -50%) scale(0.92);
}
.center-circle.countdown {
    font-size: 60px;
    color: #ff0066;
    background: radial-gradient(circle, #fff, #ff99cc);
    cursor: default;
}
.center-circle.spinning {
    font-size: 22px;
    color: #ff00ff;
    animation: pulse 0.5s infinite;
    cursor: default;
}
@keyframes pulse {
    0%, 100% { transform: translate(-50%, -50%) scale(1); }
    50% { transform: translate(-50%, -50%) scale(1.1); }
}
.message-box {
    padding: 20px;
    border-radius: 15px;
    text-align: center;
    margin: 20px auto;
    max-width: 400px;
    font-size: 17px;
    font-weight: bold;
    line-height: 1.5;
    transition: all 0.4s;
}
.message-box.waiting { background: rgba(255,255,255,0.1); color: #ccc; }
.message-box.blowing { background: linear-gradient(45deg, #11998e, #38ef7d); color: white; }
.message-box.spinning { background: linear-gradient(45deg, #00f5ff, #ff00ff); color: white; }
.message-box.winner { background: linear-gradient(135deg, #ff6b6b, #feca57); color: #333; font-size: 20px; box-shadow: 0 5px 25px rgba(255,107,107,0.5); }
.gas-meter {
    max-width: 400px;
    margin: 10px auto;
    height: 30px;
    background: rgba(255,255,255,0.1);
    border-radius: 15px;
    overflow: hidden;
    position: relative;
    display: none;
}
.gas-meter.show { display: block; }
.gas-fill {
    height: 100%;
    background: linear-gradient(90deg, #00ff00, #ffff00, #ff0000);
    width: 0%;
    transition: width 0.15s;
}
.gas-max {
    position: absolute;
    left: 0%;
    top: 0;
    bottom: 0;
    width: 3px;
    background: #fff;
    transition: left 0.15s;
}
.gas-label {
    text-align: center;
    font-size: 12px;
    color: #888;
    margin-top: 5px;
    display: none;
}
.gas-label.show { display: block; }
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
    cursor: pointer;
}
.big-start-btn {
    display: block;
    width: 90%;
    max-width: 400px;
    margin: 20px auto;
    padding: 18px;
    font-size: 20px;
    font-weight: bold;
    background: linear-gradient(45deg, #ff006e, #ff8a00, #ffce00);
    color: white;
    border: none;
    border-radius: 50px;
    cursor: pointer;
    box-shadow: 0 5px 25px rgba(255,0,110,0.5);
    text-align: center;
}
.big-start-btn:active { transform: scale(0.97); }
.big-start-btn:disabled {
    background: #555;
    opacity: 0.5;
    cursor: not-allowed;
}
.live-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #ff0000;
    border-radius: 50%;
    animation: blink 1s infinite;
    vertical-align: middle;
}
@keyframes blink {
    50% { opacity: 0.3; }
}
.count-info {
    text-align: center;
    font-size: 12px;
    color: #888;
    margin: 10px 0;
}
'''
    
    js = '''
var colors = __COLORS__;
var penalties = __PENALTIES__;
var NUM_SLOTS = 10;
var currentRotation = 0;
var lastWinner = -1;
var spinAnimationStarted = false;
var spinInterval = null;

// START 함수
function startGame() {
    console.log("[START] 버튼 클릭됨");
    var btn = document.getElementById('bigStartBtn');
    if (btn) btn.disabled = true;
    
    fetch('/start')
        .then(function(res) { 
            console.log("[START] 서버 응답:", res.status); 
        })
        .catch(function(e) { 
            console.error("[START] 에러:", e); 
            if (btn) btn.disabled = false;
        });
}

// 룰렛 빠른 회전
function startFastSpin() {
    var wheel = document.getElementById('wheel');
    wheel.style.transition = 'transform 0.1s linear';
    spinInterval = setInterval(function() {
        currentRotation += 72;
        wheel.style.transform = 'rotate(' + currentRotation + 'deg)';
    }, 80);
}

function stopSpinAndLand(targetPos) {
    var wheel = document.getElementById('wheel');
    if (spinInterval) {
        clearInterval(spinInterval);
        spinInterval = null;
    }
    var targetAngle = -(targetPos * 36);
    var currentMod = currentRotation % 360;
    var diff = targetAngle - currentMod;
    if (diff > 0) diff -= 360;
    var finalRotation = currentRotation + (3 * 360) + diff;
    
    wheel.style.transition = 'transform 3s cubic-bezier(0.17, 0.67, 0.21, 1)';
    wheel.style.transform = 'rotate(' + finalRotation + 'deg)';
    currentRotation = finalRotation;
}

function highlightSlice(index, highlight) {
    var slice = document.getElementById('slice' + index);
    if (!slice) return;
    if (highlight) {
        slice.setAttribute('stroke', '#ffffff');
        slice.setAttribute('stroke-width', '5');
    } else {
        slice.setAttribute('stroke', '#333');
        slice.setAttribute('stroke-width', '1');
    }
}

function clearAllHighlights() {
    for (var i = 0; i < NUM_SLOTS; i++) {
        highlightSlice(i, false);
    }
}

// SVG 룰렛 생성
function createRoulette() {
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
        path.setAttribute('stroke', '#333');
        path.setAttribute('stroke-width', '1');
        path.setAttribute('id', 'slice' + i);
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
        text.setAttribute('font-size', '22');
        text.setAttribute('font-weight', 'bold');
        text.textContent = (i + 1);
        svg.appendChild(text);
    }
}

// 상태 갱신
function updateUI() {
    fetch('/status').then(function(res) {
        return res.json();
    }).then(function(data) {
        var gameState = data.game_state;
        var statusEl = document.getElementById('statusTop');
        var centerEl = document.getElementById('centerCircle');
        var messageEl = document.getElementById('messageBox');
        var gasMeterEl = document.getElementById('gasMeter');
        var gasLabelEl = document.getElementById('gasLabel');
        var countEl = document.getElementById('countInfo');
        var bigBtn = document.getElementById('bigStartBtn');
        
        countEl.textContent = '총 게임 횟수: ' + data.spin_count + '회';
        
        if (gameState === 0) {
            // 대기
            statusEl.textContent = '⏸️ 대기 중';
            centerEl.className = 'center-circle';
            centerEl.innerHTML = '🎰<br>START!';
            messageEl.className = 'message-box waiting';
            messageEl.innerHTML = '🎯 START 버튼을 누르고<br>5초간 입김을 부세요!';
            gasMeterEl.classList.remove('show');
            gasLabelEl.classList.remove('show');
            clearAllHighlights();
            if (bigBtn) {
                bigBtn.disabled = false;
                bigBtn.textContent = '🎰 START!';
            }
            
        } else if (gameState === 1) {
            // 입김 측정
            statusEl.textContent = '💨 입김 측정 중!';
            centerEl.className = 'center-circle countdown';
            centerEl.innerHTML = data.blow_remaining;
            messageEl.className = 'message-box blowing';
            messageEl.innerHTML = '💨 입김을 세게 부세요!<br>최대 강도: ' + data.max_blow;
            
            gasMeterEl.classList.add('show');
            gasLabelEl.classList.add('show');
            var pct = Math.min(100, (data.sensor_diff / 30000) * 100);
            var maxPct = Math.min(100, (data.max_blow / 30000) * 100);
            document.getElementById('gasFill').style.width = pct + '%';
            document.getElementById('gasMax').style.left = maxPct + '%';
            gasLabelEl.innerHTML = '💨 현재: ' + data.sensor_diff + ' | 최대: ' + data.max_blow;
            
            if (bigBtn) {
                bigBtn.disabled = true;
                bigBtn.textContent = '💨 측정 중... ' + data.blow_remaining + '초';
            }
            
        } else if (gameState === 2) {
            // 회전 중
            statusEl.textContent = '🎰 룰렛 회전 중!';
            centerEl.className = 'center-circle spinning';
            centerEl.innerHTML = 'SPIN!';
            messageEl.className = 'message-box spinning';
            messageEl.innerHTML = '🎰 룰렛이 돌아가요!<br>두근두근...';
            gasMeterEl.classList.remove('show');
            gasLabelEl.classList.remove('show');
            
            if (!spinAnimationStarted) {
                spinAnimationStarted = true;
                lastWinner = -1;
                startFastSpin();
            }
            
            clearAllHighlights();
            highlightSlice(data.current_pos, true);
            
            if (bigBtn) {
                bigBtn.disabled = true;
                bigBtn.textContent = '🎰 회전 중...';
            }
            
        } else if (gameState === 3) {
            // 결과
            statusEl.textContent = '✅ 결과 발표!';
            centerEl.className = 'center-circle';
            centerEl.innerHTML = '🔄<br>다시!';
            messageEl.className = 'message-box winner';
            messageEl.innerHTML = '🎉 ' + (data.last_winner + 1) + '번 당첨! 🎉<br>📜 ' + penalties[data.last_winner];
            gasMeterEl.classList.remove('show');
            gasLabelEl.classList.remove('show');
            
            if (lastWinner !== data.last_winner) {
                lastWinner = data.last_winner;
                if (spinAnimationStarted) {
                    spinAnimationStarted = false;
                    stopSpinAndLand(data.last_winner);
                }
                setTimeout(function() {
                    clearAllHighlights();
                    highlightSlice(data.last_winner, true);
                }, 3000);
            }
            
            if (bigBtn) {
                bigBtn.disabled = false;
                bigBtn.textContent = '🔄 다시 시작!';
            }
        }
    }).catch(function(e) {
        console.error("[updateUI] 에러:", e);
    });
}

// 페이지 로드 완료 후 실행
window.addEventListener('load', function() {
    console.log("[INIT] 페이지 로드 완료");
    
    // 룰렛 그리기
    createRoulette();
    console.log("[INIT] 룰렛 SVG 생성 완료");
    
    // 가운데 원 클릭 이벤트
    var centerCircle = document.getElementById('centerCircle');
    centerCircle.addEventListener('click', function() {
        console.log("[CLICK] 가운데 원 클릭!");
        startGame();
    });
    
    // 큰 START 버튼 클릭 이벤트
    var bigBtn = document.getElementById('bigStartBtn');
    bigBtn.addEventListener('click', function() {
        console.log("[CLICK] 큰 START 버튼 클릭!");
        startGame();
    });
    
    console.log("[INIT] 이벤트 리스너 등록 완료");
    
    // 0.3초마다 갱신 시작
    setInterval(updateUI, 300);
    updateUI();
    console.log("[INIT] 갱신 루프 시작!");
});
'''
    
    js = js.replace("__COLORS__", colors_js)
    js = js.replace("__PENALTIES__", penalties_js)
    
    html = '<!DOCTYPE html><html><head><meta charset="utf-8">'
    html += '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    html += '<title>운명의 룰렛</title>'
    html += '<style>' + css + '</style>'
    html += '</head><body>'
    
    html += '<h1>🎰 운명의 룰렛 🎰</h1>'
    html += '<p class="subtitle"><span class="live-dot"></span> LIVE | MQ-2 + WS2813</p>'
    html += '<div class="status-top" id="statusTop">⏸️ 대기 중</div>'
    
    html += '<div class="roulette-container">'
    html += '<div class="pointer"></div>'
    html += '<div class="roulette-wheel" id="wheel"><svg id="wheelSvg" viewBox="-100 -100 200 200"></svg></div>'
    html += '<div class="center-circle" id="centerCircle">🎰<br>START!</div>'
    html += '</div>'
    
    # 큰 START 버튼 (확실하게 누를 수 있도록!)
    html += '<button class="big-start-btn" id="bigStartBtn">🎰 START!</button>'
    
    html += '<div class="message-box waiting" id="messageBox">🎯 START 버튼을 누르고<br>5초간 입김을 부세요!</div>'
    
    html += '<div class="gas-meter" id="gasMeter"><div class="gas-fill" id="gasFill"></div><div class="gas-max" id="gasMax"></div></div>'
    html += '<div class="gas-label" id="gasLabel"></div>'
    
    html += '<div class="count-info" id="countInfo">총 게임 횟수: 0회</div>'
    
    html += '<div class="penalties-section">'
    html += '<h2>📝 벌칙 설정</h2>'
    html += '<form action="/save" method="POST">'
    html += rows
    html += '<button type="submit" class="save-btn">💾 저장하기</button>'
    html += '</form></div>'
    
    html += '<script>' + js + '</script>'
    html += '</body></html>'
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
    print("웹 서버 시작! (Core 1)")
    
    while True:
        try:
            cl, addr = s.accept()
            cl.settimeout(3.0)
            request = cl.recv(2048).decode('utf-8')
            first_line = request.split('\r\n')[0]
            
            # 상태 JSON
            if 'GET /status' in first_line:
                with lock:
                    json_data = '{'
                    json_data += '"game_state":' + str(state["game_state"]) + ','
                    json_data += '"current_pos":' + str(state["current_pos"]) + ','
                    json_data += '"last_winner":' + str(state["last_winner"]) + ','
                    json_data += '"sensor_diff":' + str(state["sensor_diff"]) + ','
                    json_data += '"max_blow":' + str(state["max_blow"]) + ','
                    json_data += '"blow_remaining":' + str(state["blow_remaining"]) + ','
                    json_data += '"spin_count":' + str(state["spin_count"])
                    json_data += '}'
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n')
                cl.send(json_data)
            
            # START 트리거
            elif 'GET /start' in first_line:
                print(">>> START 요청 받음!")
                with lock:
                    if state['game_state'] in (GAME_IDLE, GAME_RESULT):
                        state['start_trigger'] = True
                        print(">>> 게임 시작 신호 설정!")
                    else:
                        print(">>> 이미 게임 진행 중...")
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nOK')
            
            # 벌칙 저장
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
            
            # 메인 페이지
            else:
                html = generate_main_page()
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n')
                chunk_size = 1024
                for i in range(0, len(html), chunk_size):
                    cl.send(html[i:i+chunk_size])
            
            cl.close()
        except Exception as e:
            try:
                cl.close()
            except:
                pass

# ============================================
# 게임 로직
# ============================================
def measure_blow(baseline):
    print("\n💨 입김 측정 시작! (5초)")
    
    with lock:
        state['game_state'] = GAME_BLOWING
        state['max_blow'] = 0
        state['blow_remaining'] = 5
    
    max_blow = 0
    start_time = time.ticks_ms()
    
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start_time)
        remaining = 5 - (elapsed // 1000)
        
        if elapsed >= 5000:
            break
        
        gas_value = mq2.read_u16()
        diff = max(0, gas_value - baseline)
        
        if diff > max_blow:
            max_blow = diff
        
        power_level = min(diff / 30000, 1.0)
        show_countdown(power_level)
        
        with lock:
            state['sensor_diff'] = diff
            state['max_blow'] = max_blow
            state['blow_remaining'] = max(0, remaining)
        
        time.sleep(0.05)
    
    print("측정 완료! 최대 입김:", max_blow)
    return max_blow

def spin_roulette(power):
    print("🎰 룰렛 회전! 파워:", round(power, 2))
    
    with lock:
        state['game_state'] = GAME_SPINNING
        state['spin_count'] += 1
    
    total_steps = int(20 + power * 80)
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
        state['game_state'] = GAME_RESULT
    
    print("=" * 45)
    print("🎉 당첨!", position + 1, "번")
    print("📜 벌칙:", penalties[position])
    print("=" * 45)
    
    winner_celebration(position)
    show_pointer(position)

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
    print("\n=== 🎰 운명의 룰렛 시작 ===\n")
    
    ip = connect_wifi()
    if not ip:
        return
    
    _thread.start_new_thread(web_server_thread, ())
    time.sleep(1)
    
    baseline = calibrate()
    with lock:
        state['baseline'] = baseline
    
    show_idle()
    print("\n준비 완료! 브라우저에서 START 버튼을 누르세요!")
    print("URL: http://" + ip + "\n")
    
    while True:
        with lock:
            start_trigger = state['start_trigger']
            current_game = state['game_state']
        
        if start_trigger and current_game in (GAME_IDLE, GAME_RESULT):
            with lock:
                state['start_trigger'] = False
            
            print("\n>>> 게임 시작!")
            
            # 1. 5초 입김 측정
            max_blow = measure_blow(baseline)
            
            # 2. 강도 계산
            power = min(max_blow / 30000, 1.0)
            if power < 0.1:
                power = 0.1
                print("입김 약함 → 최소 회전")
            
            # 3. 룰렛 회전
            spin_roulette(power)
            
            # 4. 결과 5초 표시
            time.sleep(5)
            
            with lock:
                state['game_state'] = GAME_IDLE
            show_idle()
            print("\n>>> 대기 중. START 버튼을 다시 눌러주세요!\n")
        else:
            gas_value = mq2.read_u16()
            diff = max(0, gas_value - baseline)
            with lock:
                state['sensor_diff'] = diff
            time.sleep(0.1)

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
