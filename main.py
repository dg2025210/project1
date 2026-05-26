from machine import Pin, ADC
from neopixel import NeoPixel
import network
import socket
import time
import random
import math
import _thread
import wifi_config as cfg

# WS2813 Mini 타이밍
TIMING = (280, 515, 515, 745)
led = NeoPixel(Pin(cfg.LED_PIN), cfg.NUM_LEDS, timing=TIMING)
mq2 = ADC(Pin(cfg.MQ2_PIN))

# 가능한 모든 색상 (최대 10개)
ALL_SLOT_COLORS = [
    (255, 50, 50),    (255, 140, 0),    (255, 230, 0),    (150, 255, 0),
    (0, 220, 0),      (0, 230, 180),    (0, 180, 255),    (60, 80, 255),
    (170, 80, 255),   (255, 60, 200),
]

# 기본 벌칙 (최대 10개)
ALL_PENALTIES = [
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
    'num_slots': 8,         # 활성 벌칙 개수 (2~10)
    'penalties': list(ALL_PENALTIES),
}

lock = _thread.allocate_lock()

# ============================================
# LED 헬퍼 (현재 활성 칸 수에 맞춰)
# ============================================
def get_active_colors():
    with lock:
        n = state['num_slots']
    # NUM_LEDS(10)를 num_slots개로 나눠서 배치
    return ALL_SLOT_COLORS[:n]

def clear():
    for i in range(cfg.NUM_LEDS):
        led[i] = (0, 0, 0)
    led.write()

def show_idle():
    """대기 상태: 활성 칸 수에 맞춰 LED 표시"""
    with lock:
        n = state['num_slots']
    
    # LED 10개를 n개의 칸으로 나누기
    leds_per_slot = cfg.NUM_LEDS // n
    extra = cfg.NUM_LEDS - (leds_per_slot * n)
    
    led_idx = 0
    for slot in range(n):
        count = leds_per_slot + (1 if slot < extra else 0)
        c = ALL_SLOT_COLORS[slot]
        for _ in range(count):
            if led_idx < cfg.NUM_LEDS:
                led[led_idx] = (c[0] // 12, c[1] // 12, c[2] // 12)
                led_idx += 1
    led.write()

def show_pointer(position):
    """회전 중인 칸 강조"""
    with lock:
        n = state['num_slots']
    
    leds_per_slot = cfg.NUM_LEDS // n
    extra = cfg.NUM_LEDS - (leds_per_slot * n)
    
    led_idx = 0
    for slot in range(n):
        count = leds_per_slot + (1 if slot < extra else 0)
        c = ALL_SLOT_COLORS[slot]
        for _ in range(count):
            if led_idx < cfg.NUM_LEDS:
                if slot == position:
                    led[led_idx] = c
                else:
                    led[led_idx] = (c[0] // 18, c[1] // 18, c[2] // 18)
                led_idx += 1
    led.write()

def show_countdown(power_level):
    """입김 강도에 따라 LED 차오름"""
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
    c = ALL_SLOT_COLORS[slot]
    for _ in range(5):
        clear()
        time.sleep(0.12)
        for i in range(cfg.NUM_LEDS):
            led[i] = c
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
# WiFi
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
    print("WiFi 연결!  http://" + ip)
    print("=" * 45)
    for i in range(cfg.NUM_LEDS):
        led[i] = (0, 50, 0)
    led.write()
    time.sleep(0.8)
    clear()
    return ip

# ============================================
# HTML 생성
# ============================================
def generate_main_page():
    with lock:
        n = state['num_slots']
        current_penalties = list(state['penalties'])
    
    # 활성 색상
    active_colors = ALL_SLOT_COLORS[:n]
    
    # 벌칙 입력 (현재 활성 개수만)
    rows = ""
    for i in range(n):
        c = ALL_SLOT_COLORS[i]
        hex_color = "#%02x%02x%02x" % (c[0], c[1], c[2])
        rows += '<div class="slot" style="border-left: 6px solid ' + hex_color + ';">'
        rows += '<label>' + str(i+1) + '번 칸</label>'
        rows += '<input type="text" name="p' + str(i) + '" value="' + current_penalties[i] + '" maxlength="50">'
        rows += '</div>'
    
    # JS용 데이터
    colors_js = "[" + ",".join(["[%d,%d,%d]" % (c[0], c[1], c[2]) for c in active_colors]) + "]"
    
    penalty_items = []
    for p in current_penalties[:n]:
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
.slot-selector {
    max-width: 400px;
    margin: 0 auto 15px;
    background: rgba(0,0,0,0.4);
    padding: 12px 15px;
    border-radius: 10px;
    border: 2px solid #ff00ff;
}
.slot-selector label {
    display: block;
    color: #ffd700;
    font-weight: bold;
    margin-bottom: 8px;
    text-align: center;
}
.slot-buttons {
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 5px;
}
.slot-btn {
    width: 38px;
    height: 38px;
    border: 2px solid #555;
    background: rgba(255,255,255,0.1);
    color: white;
    border-radius: 50%;
    font-weight: bold;
    cursor: pointer;
    font-size: 14px;
}
.slot-btn.active {
    background: linear-gradient(45deg, #ff006e, #ffce00);
    border-color: #ffd700;
    box-shadow: 0 0 15px rgba(255,215,0,0.5);
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
}
.center-circle:active { transform: translate(-50%, -50%) scale(0.92); }
.center-circle.countdown {
    font-size: 60px;
    color: #ff0066;
    background: radial-gradient(circle, #fff, #ff99cc);
}
.center-circle.spinning {
    font-size: 22px;
    color: #ff00ff;
    animation: pulse 0.5s infinite;
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
.big-start-btn:disabled { background: #555; opacity: 0.5; cursor: not-allowed; }
.live-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    background: #ff0000;
    border-radius: 50%;
    animation: blink 1s infinite;
    vertical-align: middle;
}
@keyframes blink { 50% { opacity: 0.3; } }
.count-info { text-align: center; font-size: 12px; color: #888; margin: 10px 0; }
'''
    
    js = '''
var colors = __COLORS__;
var penalties = __PENALTIES__;
var NUM_SLOTS = __NUM_SLOTS__;
var currentRotation = 0;
var lastWinner = -1;
var spinAnimationStarted = false;
var spinInterval = null;

function startGame() {
    console.log("[START] 클릭");
    var btn = document.getElementById('bigStartBtn');
    if (btn) btn.disabled = true;
    
    fetch('/start')
        .then(function(res) { console.log("[START] 응답:", res.status); })
        .catch(function(e) { 
            console.error("[START] 에러:", e); 
            if (btn) btn.disabled = false;
        });
}

function changeSlots(n) {
    console.log("[SLOTS] 변경:", n);
    fetch('/slots?n=' + n)
        .then(function(res) {
            // 페이지 새로고침 (벌칙 개수가 바뀌었으니)
            window.location.reload();
        })
        .catch(function(e) { console.error(e); });
}

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
    var sliceAngle = 360 / NUM_SLOTS;
    var targetAngle = -(targetPos * sliceAngle);
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

function createRoulette() {
    var svg = document.getElementById('wheelSvg');
    svg.innerHTML = '';  // 기존 슬라이스 제거
    var sliceAngle = 360 / NUM_SLOTS;
    
    for (var i = 0; i < NUM_SLOTS; i++) {
        var startAngle = (i * sliceAngle - 90 - sliceAngle/2) * Math.PI / 180;
        var endAngle = ((i+1) * sliceAngle - 90 - sliceAngle/2) * Math.PI / 180;
        
        var x1 = Math.cos(startAngle) * 95;
        var y1 = Math.sin(startAngle) * 95;
        var x2 = Math.cos(endAngle) * 95;
        var y2 = Math.sin(endAngle) * 95;
        
        var largeArc = sliceAngle > 180 ? 1 : 0;
        
        var c = colors[i];
        var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        var d = 'M 0 0 L ' + x1 + ' ' + y1 + ' A 95 95 0 ' + largeArc + ' 1 ' + x2 + ' ' + y2 + ' Z';
        path.setAttribute('d', d);
        path.setAttribute('fill', 'rgb(' + c[0] + ',' + c[1] + ',' + c[2] + ')');
        path.setAttribute('stroke', '#333');
        path.setAttribute('stroke-width', '1');
        path.setAttribute('id', 'slice' + i);
        svg.appendChild(path);
        
        var midAngle = (i * sliceAngle - 90) * Math.PI / 180;
        var textRadius = NUM_SLOTS <= 5 ? 60 : 70;
        var tx = Math.cos(midAngle) * textRadius;
        var ty = Math.sin(midAngle) * textRadius;
        var text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', tx);
        text.setAttribute('y', ty);
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('dominant-baseline', 'middle');
        text.setAttribute('fill', 'white');
        text.setAttribute('font-size', NUM_SLOTS <= 5 ? '30' : '22');
        text.setAttribute('font-weight', 'bold');
        text.textContent = (i + 1);
        svg.appendChild(text);
    }
}

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
            statusEl.textContent = '⏸️ 대기 중';
            centerEl.className = 'center-circle';
            centerEl.innerHTML = '🎰<br>START!';
            messageEl.className = 'message-box waiting';
            messageEl.innerHTML = '🎯 START를 누르고<br>5초간 입김을 부세요!';
            gasMeterEl.classList.remove('show');
            gasLabelEl.classList.remove('show');
            clearAllHighlights();
            if (bigBtn) {
                bigBtn.disabled = false;
                bigBtn.textContent = '🎰 START!';
            }
        } else if (gameState === 1) {
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
    }).catch(function(e) { console.error(e); });
}

window.addEventListener('load', function() {
    console.log("[INIT] 페이지 로드");
    createRoulette();
    
    var centerCircle = document.getElementById('centerCircle');
    centerCircle.addEventListener('click', startGame);
    
    var bigBtn = document.getElementById('bigStartBtn');
    bigBtn.addEventListener('click', startGame);
    
    // 슬롯 버튼들
    var slotBtns = document.querySelectorAll('.slot-btn');
    for (var i = 0; i < slotBtns.length; i++) {
        (function(btn) {
            btn.addEventListener('click', function() {
                changeSlots(parseInt(btn.dataset.num));
            });
        })(slotBtns[i]);
    }
    
    setInterval(updateUI, 300);
    updateUI();
    console.log("[INIT] 완료");
});
'''
    
    js = js.replace("__COLORS__", colors_js)
    js = js.replace("__PENALTIES__", penalties_js)
    js = js.replace("__NUM_SLOTS__", str(n))
    
    # 슬롯 개수 선택 버튼
    slot_buttons = ""
    for i in range(2, 11):
        active_class = " active" if i == n else ""
        slot_buttons += '<button class="slot-btn' + active_class + '" data-num="' + str(i) + '">' + str(i) + '</button>'
    
    html = '<!DOCTYPE html><html><head><meta charset="utf-8">'
    html += '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    html += '<title>운명의 룰렛</title>'
    html += '<style>' + css + '</style>'
    html += '</head><body>'
    
    html += '<h1>🎰 운명의 룰렛 🎰</h1>'
    html += '<p class="subtitle"><span class="live-dot"></span> LIVE | MQ-2 + WS2813</p>'
    html += '<div class="status-top" id="statusTop">⏸️ 대기 중</div>'
    
    # 슬롯 개수 선택
    html += '<div class="slot-selector">'
    html += '<label>🎲 벌칙 개수 선택 (현재: ' + str(n) + '개)</label>'
    html += '<div class="slot-buttons">' + slot_buttons + '</div>'
    html += '</div>'
    
    html += '<div class="roulette-container">'
    html += '<div class="pointer"></div>'
    html += '<div class="roulette-wheel" id="wheel"><svg id="wheelSvg" viewBox="-100 -100 200 200"></svg></div>'
    html += '<div class="center-circle" id="centerCircle">🎰<br>START!</div>'
    html += '</div>'
    
    html += '<button class="big-start-btn" id="bigStartBtn">🎰 START!</button>'
    
    html += '<div class="message-box waiting" id="messageBox">🎯 START를 누르고<br>5초간 입김을 부세요!</div>'
    
    html += '<div class="gas-meter" id="gasMeter"><div class="gas-fill" id="gasFill"></div><div class="gas-max" id="gasMax"></div></div>'
    html += '<div class="gas-label" id="gasLabel"></div>'
    
    html += '<div class="count-info" id="countInfo">총 게임 횟수: 0회</div>'
    
    html += '<div class="penalties-section">'
    html += '<h2>📝 벌칙 설정 (' + str(n) + '개)</h2>'
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

def parse_query(path):
    """?n=5 같은 쿼리스트링 파싱"""
    data = {}
    if '?' in path:
        query = path.split('?', 1)[1]
        for pair in query.split('&'):
            if '=' in pair:
                key, value = pair.split('=', 1)
                data[key] = value
    return data

# ============================================
# 웹 서버
# ============================================
def web_server_thread():
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
            parts = first_line.split(' ')
            method = parts[0] if len(parts) > 0 else ''
            path = parts[1] if len(parts) > 1 else '/'
            
            # 상태 JSON
            if path.startswith('/status'):
                with lock:
                    json_data = '{'
                    json_data += '"game_state":' + str(state["game_state"]) + ','
                    json_data += '"current_pos":' + str(state["current_pos"]) + ','
                    json_data += '"last_winner":' + str(state["last_winner"]) + ','
                    json_data += '"sensor_diff":' + str(state["sensor_diff"]) + ','
                    json_data += '"max_blow":' + str(state["max_blow"]) + ','
                    json_data += '"blow_remaining":' + str(state["blow_remaining"]) + ','
                    json_data += '"spin_count":' + str(state["spin_count"]) + ','
                    json_data += '"num_slots":' + str(state["num_slots"])
                    json_data += '}'
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n')
                cl.send(json_data)
            
            # START
            elif path.startswith('/start'):
                print(">>> START 요청!")
                with lock:
                    if state['game_state'] in (GAME_IDLE, GAME_RESULT):
                        state['start_trigger'] = True
                        print(">>> 게임 시작!")
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nOK')
            
            # 슬롯 개수 변경
            elif path.startswith('/slots'):
                query = parse_query(path)
                if 'n' in query:
                    try:
                        n = int(query['n'])
                        if 2 <= n <= 10:
                            with lock:
                                state['num_slots'] = n
                                state['last_winner'] = -1  # 결과 초기화
                                state['game_state'] = GAME_IDLE
                            print(">>> 슬롯 개수 변경:", n)
                    except:
                        pass
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nOK')
            
            # 벌칙 저장
            elif 'POST' in method and '/save' in path:
                if '\r\n\r\n' in request:
                    body = request.split('\r\n\r\n', 1)[1]
                    data = parse_post(body)
                    with lock:
                        n = state['num_slots']
                        for i in range(n):
                            key = 'p' + str(i)
                            if key in data and data[key].strip():
                                state['penalties'][i] = data[key].strip()
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
# 입김 측정 (절대값 기반!) ⭐
# ============================================
def measure_blow(baseline):
    """5초간 입김 측정 - 베이스라인에서 멀어진 정도(절대값)"""
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
        
        # ⭐ 핵심 수정: 베이스라인과의 차이를 절대값으로!
        # 입김이 수치를 올리든 내리든 둘 다 "변화"로 인식
        diff = abs(gas_value - baseline)
        
        if diff > max_blow:
            max_blow = diff
        
        power_level = min(diff / 20000, 1.0)
        show_countdown(power_level)
        
        with lock:
            state['sensor_diff'] = diff
            state['max_blow'] = max_blow
            state['blow_remaining'] = max(0, remaining)
        
        time.sleep(0.05)
    
    print("측정 완료! 최대 변화량:", max_blow)
    return max_blow

# ============================================
# 룰렛 회전
# ============================================
def spin_roulette(power):
    with lock:
        n = state['num_slots']
    
    print("🎰 룰렛 회전! 파워:", round(power, 2), "슬롯 수:", n)
    
    with lock:
        state['game_state'] = GAME_SPINNING
        state['spin_count'] += 1
    
    total_steps = int(15 + power * 80)
    position = random.randint(0, n - 1)
    
    for step in range(total_steps):
        position = (position + 1) % n
        show_pointer(position)
        
        with lock:
            state['current_pos'] = position
        
        progress = step / total_steps
        delay = 0.04 + (progress ** 2.5) * 0.5
        time.sleep(delay)
    
    with lock:
        state['last_winner'] = position
        state['game_state'] = GAME_RESULT
        winning_penalty = state['penalties'][position]
    
    print("=" * 45)
    print("🎉 당첨!", position + 1, "번")
    print("📜 벌칙:", winning_penalty)
    print("=" * 45)
    
    winner_celebration(position)
    show_pointer(position)

# ============================================
# 캘리브레이션
# ============================================
def calibrate():
    print("MQ-2 센서 예열 중... (가만히 있으세요!)")
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
    print("\n=== 🎰 운명의 룰렛 ===\n")
    
    ip = connect_wifi()
    if not ip:
        return
    
    _thread.start_new_thread(web_server_thread, ())
    time.sleep(1)
    
    baseline = calibrate()
    with lock:
        state['baseline'] = baseline
    
    show_idle()
    print("\n준비 완료!  http://" + ip + "\n")
    
    while True:
        with lock:
            start_trigger = state['start_trigger']
            current_game = state['game_state']
        
        if start_trigger and current_game in (GAME_IDLE, GAME_RESULT):
            with lock:
                state['start_trigger'] = False
            
            print("\n>>> 게임 시작!")
            
            max_blow = measure_blow(baseline)
            
            # 변화량 20000을 최대치로 (조절 가능)
            power = min(max_blow / 20000, 1.0)
            if power < 0.1:
                power = 0.1
            
            spin_roulette(power)
            
            time.sleep(5)
            
            with lock:
                state['game_state'] = GAME_IDLE
            show_idle()
            print("\n>>> 대기 중\n")
        else:
            gas_value = mq2.read_u16()
            diff = abs(gas_value - baseline)  # 평상시에도 절대값
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
