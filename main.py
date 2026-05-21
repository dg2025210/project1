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
GAME_IDLE = 0       # 대기
GAME_BLOWING = 1    # 입김 측정 중 (5초)
GAME_SPINNING = 2   # 룰렛 회전 중
GAME_RESULT = 3     # 결과 표시

state = {
    'game_state': GAME_IDLE,
    'current_pos': 0,
    'last_winner': -1,
    'sensor_diff': 0,
    'spin_count': 0,
    'start_trigger': False,
    'blow_remaining': 0,    # 남은 측정 시간
    'blow_power': 0,        # 측정된 입김 강도 (누적)
    'max_blow': 0,          # 최대 입김값
    'baseline': 0,
    'rotation_angle': 0,    # 룰렛 회전 각도
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

def show_countdown(seconds_left, power_level):
    """카운트다운 중 LED 표시 - 입김 셀수록 LED 밝아짐"""
    # power_level: 0.0 ~ 1.0
    num_lit = int(cfg.NUM_LEDS * power_level)
    
    for i in range(cfg.NUM_LEDS):
        if i < num_lit:
            # 입김 강도에 따른 색상 (초록 → 노랑 → 빨강)
            if power_level < 0.33:
                led[i] = (0, 200, 0)
            elif power_level < 0.66:
                led[i] = (200, 200, 0)
            else:
                led[i] = (255, 50, 0)
        else:
            led[i] = (5, 5, 20)  # 어두운 파랑
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
    print("WiFi 연결 성공!  IP:", ip)
    print("접속:  http://" + ip)
    print("=" * 45)
    
    for i in range(cfg.NUM_LEDS):
        led[i] = (0, 50, 0)
    led.write()
    time.sleep(0.8)
    clear()
    return ip

# ============================================
# HTML 페이지 (서버에서 직접 그리기 + 자동 새로고침)
# ============================================
def generate_main_page():
    with lock:
        game = state['game_state']
        current_pos = state['current_pos']
        last_winner = state['last_winner']
        sensor_diff = state['sensor_diff']
        spin_count = state['spin_count']
        blow_remaining = state['blow_remaining']
        max_blow = state['max_blow']
        rotation_angle = state['rotation_angle']
    
    # 벌칙 입력 폼
    rows = ""
    for i in range(cfg.NUM_LEDS):
        c = SLOT_COLORS[i]
        hex_color = "#%02x%02x%02x" % (c[0], c[1], c[2])
        rows += '<div class="slot" style="border-left: 6px solid ' + hex_color + ';">'
        rows += '<label>' + str(i+1) + '번 칸</label>'
        rows += '<input type="text" name="p' + str(i) + '" value="' + penalties[i] + '" maxlength="50">'
        rows += '</div>'
    
    # SVG 룰렛 슬라이스
    svg_slices = ""
    for i in range(cfg.NUM_LEDS):
        slice_angle = 36
        start_angle = (i * slice_angle - 90 - slice_angle/2) * math.pi / 180
        end_angle = ((i+1) * slice_angle - 90 - slice_angle/2) * math.pi / 180
        
        x1 = math.cos(start_angle) * 95
        y1 = math.sin(start_angle) * 95
        x2 = math.cos(end_angle) * 95
        y2 = math.sin(end_angle) * 95
        
        c = SLOT_COLORS[i]
        fill_color = "rgb(%d,%d,%d)" % (c[0], c[1], c[2])
        
        # 당첨/회전 중인 칸 강조
        if (game == GAME_SPINNING and i == current_pos) or (game == GAME_RESULT and i == last_winner):
            stroke = '#ffffff'
            stroke_w = '5'
        else:
            stroke = '#333'
            stroke_w = '1'
        
        path_d = "M 0 0 L %.1f %.1f A 95 95 0 0 1 %.1f %.1f Z" % (x1, y1, x2, y2)
        svg_slices += '<path d="' + path_d + '" fill="' + fill_color + '" stroke="' + stroke + '" stroke-width="' + stroke_w + '"/>'
        
        # 숫자
        mid_angle = (i * slice_angle - 90) * math.pi / 180
        tx = math.cos(mid_angle) * 65
        ty = math.sin(mid_angle) * 65
        svg_slices += '<text x="%.1f" y="%.1f" text-anchor="middle" dominant-baseline="middle" fill="white" font-size="22" font-weight="bold">%d</text>' % (tx, ty, i+1)
    
    # 상태에 따라 화면 구성
    if game == GAME_IDLE:
        # 대기 상태
        status_text = "⏸️ 대기 중"
        center_box = '<a href="/start" class="start-btn">🎰 START!</a>'
        message = '🎯 START를 누르고 5초간 입김을 부세요!'
        message_class = 'waiting'
        refresh = "2"
        
    elif game == GAME_BLOWING:
        # 입김 측정 중 (5초 카운트다운)
        status_text = "💨 입김 측정 중! " + str(blow_remaining) + "초 남음"
        center_box = '<div class="countdown">' + str(blow_remaining) + '</div>'
        # 입김 강도 시각화
        power_pct = min(100, (max_blow / 30000) * 100)
        message = '💨 입김을 세게 부세요!<br>현재 강도: ' + str(int(power_pct)) + '%'
        message_class = 'blowing'
        refresh = "0.5"
        
    elif game == GAME_SPINNING:
        # 룰렛 회전 중
        status_text = "🎰 룰렛 회전 중!"
        center_box = '<div class="spinning-text">SPIN!</div>'
        message = '🎰 룰렛이 돌아가고 있어요!<br>두근두근...'
        message_class = 'spinning'
        refresh = "0.3"
        
    else:  # GAME_RESULT
        # 결과 표시
        status_text = "✅ 결과!"
        center_box = '<a href="/start" class="start-btn">🔄 다시 하기</a>'
        message = '🎉 ' + str(last_winner + 1) + '번 당첨! 🎉<br>📜 ' + penalties[last_winner]
        message_class = 'winner'
        refresh = "5"
    
    # 가스 미터
    gas_pct = min(100, (sensor_diff / 30000) * 100)
    max_pct = min(100, (max_blow / 30000) * 100)
    
    html = '<!DOCTYPE html><html><head><meta charset="utf-8">'
    html += '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
    html += '<meta http-equiv="refresh" content="' + refresh + '">'
    html += '<title>운명의 룰렛</title>'
    html += '<style>'
    html += '* { box-sizing: border-box; margin: 0; padding: 0; }'
    html += 'body { font-family: sans-serif; background: radial-gradient(circle at center, #2d1b4e, #0f0524); color: white; padding: 15px; min-height: 100vh; }'
    html += 'h1 { text-align: center; font-size: 28px; text-shadow: 0 0 20px #ff00ff; margin-bottom: 5px; }'
    html += '.subtitle { text-align: center; color: #aaa; font-size: 12px; margin-bottom: 15px; }'
    html += '.status-top { text-align: center; font-size: 16px; color: #ffd700; font-weight: bold; margin-bottom: 15px; padding: 10px; background: rgba(0,0,0,0.3); border-radius: 10px; }'
    html += '.roulette-container { position: relative; width: 320px; height: 320px; margin: 20px auto; }'
    html += '.roulette-wheel { width: 100%; height: 100%; border-radius: 50%; box-shadow: 0 0 40px rgba(255,0,255,0.5); transform: rotate(' + str(rotation_angle) + 'deg); transition: transform 0.3s ease-out; }'
    html += '.roulette-wheel svg { width: 100%; height: 100%; display: block; }'
    html += '.pointer { position: absolute; top: -15px; left: 50%; transform: translateX(-50%); width: 0; height: 0; border-left: 20px solid transparent; border-right: 20px solid transparent; border-top: 35px solid #ffd700; filter: drop-shadow(0 0 10px rgba(255,215,0,0.8)); z-index: 10; }'
    html += '.center-circle { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 80px; height: 80px; background: radial-gradient(circle, #fff, #ffd700); border-radius: 50%; box-shadow: 0 0 20px #ffd700; z-index: 5; display: flex; align-items: center; justify-content: center; font-size: 28px; font-weight: bold; color: #333; }'
    html += '.countdown { font-size: 40px; color: #ff0066; }'
    html += '.spinning-text { font-size: 22px; color: #ff00ff; animation: pulse 0.5s infinite; }'
    html += '@keyframes pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.1); } }'
    html += '.start-btn { display: block; width: 90%; max-width: 350px; margin: 20px auto; padding: 20px; font-size: 22px; font-weight: bold; background: linear-gradient(45deg, #ff006e, #ff8a00, #ffce00); color: white; border: none; border-radius: 50px; text-decoration: none; text-align: center; box-shadow: 0 5px 25px rgba(255,0,110,0.5); }'
    html += '.center-circle .start-btn { width: auto; margin: 0; padding: 8px 16px; font-size: 14px; border-radius: 20px; }'
    html += '.message-box { padding: 20px; border-radius: 15px; text-align: center; margin: 20px auto; max-width: 400px; font-size: 17px; font-weight: bold; line-height: 1.5; }'
    html += '.message-box.waiting { background: rgba(255,255,255,0.1); color: #ccc; }'
    html += '.message-box.blowing { background: linear-gradient(45deg, #11998e, #38ef7d); color: white; animation: pulse 0.6s infinite; }'
    html += '.message-box.spinning { background: linear-gradient(45deg, #00f5ff, #ff00ff); color: white; animation: pulse 0.5s infinite; }'
    html += '.message-box.winner { background: linear-gradient(135deg, #ff6b6b, #feca57); color: #333; font-size: 20px; box-shadow: 0 5px 25px rgba(255,107,107,0.5); }'
    html += '.gas-meter { max-width: 400px; margin: 10px auto; height: 30px; background: rgba(255,255,255,0.1); border-radius: 15px; overflow: hidden; position: relative; }'
    html += '.gas-fill { height: 100%; background: linear-gradient(90deg, #00ff00, #ffff00, #ff0000); width: ' + str(gas_pct) + '%; transition: width 0.3s; }'
    html += '.gas-max { position: absolute; left: ' + str(max_pct) + '%; top: 0; bottom: 0; width: 3px; background: #fff; }'
    html += '.gas-label { text-align: center; font-size: 12px; color: #888; margin-top: 5px; }'
    html += '.penalties-section { max-width: 400px; margin: 30px auto 0; }'
    html += 'h2 { font-size: 18px; color: #ffd700; margin-bottom: 10px; text-align: center; }'
    html += '.slot { background: rgba(255,255,255,0.06); padding: 10px 12px; margin: 8px 0; border-radius: 8px; }'
    html += '.slot label { display: block; font-weight: bold; margin-bottom: 4px; color: #ffd700; font-size: 12px; }'
    html += '.slot input { width: 100%; padding: 8px; font-size: 14px; border: none; border-radius: 5px; }'
    html += '.save-btn { width: 100%; padding: 14px; font-size: 16px; font-weight: bold; background: linear-gradient(45deg, #667eea, #764ba2); color: white; border: none; border-radius: 10px; margin-top: 12px; }'
    html += '.live-dot { display: inline-block; width: 8px; height: 8px; background: #ff0000; border-radius: 50%; animation: blink 1s infinite; vertical-align: middle; }'
    html += '@keyframes blink { 50% { opacity: 0.3; } }'
    html += '.count-info { text-align: center; font-size: 12px; color: #888; margin: 10px 0; }'
    html += '</style></head><body>'
    
    html += '<h1>🎰 운명의 룰렛 🎰</h1>'
    html += '<p class="subtitle"><span class="live-dot"></span> 자동 새로고침 중 | MQ-2 + WS2813</p>'
    html += '<div class="status-top">' + status_text + '</div>'
    
    html += '<div class="roulette-container">'
    html += '<div class="pointer"></div>'
    html += '<div class="roulette-wheel"><svg viewBox="-100 -100 200 200">' + svg_slices + '</svg></div>'
    html += '<div class="center-circle">' + center_box + '</div>'
    html += '</div>'
    
    html += '<div class="message-box ' + message_class + '">' + message + '</div>'
    
    # 입김 측정 중일 때만 강도 표시
    if game == GAME_BLOWING:
        html += '<div class="gas-meter"><div class="gas-fill"></div><div class="gas-max"></div></div>'
        html += '<div class="gas-label">💨 현재: ' + str(sensor_diff) + ' | 최대: ' + str(max_blow) + '</div>'
    
    html += '<div class="count-info">총 게임 횟수: ' + str(spin_count) + '회</div>'
    
    html += '<div class="penalties-section">'
    html += '<h2>📝 벌칙 설정</h2>'
    html += '<form action="/save" method="POST">'
    html += rows
    html += '<button type="submit" class="save-btn">💾 저장하기</button>'
    html += '</form></div>'
    
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
    print("웹 서버 시작!")
    
    while True:
        try:
            cl, addr = s.accept()
            cl.settimeout(3.0)
            request = cl.recv(2048).decode('utf-8')
            first_line = request.split('\r\n')[0]
            
            # START 버튼
            if 'GET /start' in first_line:
                with lock:
                    if state['game_state'] in (GAME_IDLE, GAME_RESULT):
                        state['start_trigger'] = True
                cl.send('HTTP/1.0 303 See Other\r\nLocation: /\r\n\r\n')
            
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
# 입김 측정 (5초)
# ============================================
def measure_blow(baseline):
    """5초간 입김 측정, 최대값 반환"""
    print("\n💨 입김 측정 시작! (5초)")
    
    with lock:
        state['game_state'] = GAME_BLOWING
        state['max_blow'] = 0
    
    max_blow = 0
    start_time = time.ticks_ms()
    
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start_time)
        remaining = 5 - (elapsed // 1000)
        
        if elapsed >= 5000:
            break
        
        # 센서 읽기
        gas_value = mq2.read_u16()
        diff = max(0, gas_value - baseline)
        
        if diff > max_blow:
            max_blow = diff
        
        # 현재 강도에 따라 LED 표시
        power_level = min(diff / 30000, 1.0)
        show_countdown(remaining, power_level)
        
        # 상태 업데이트
        with lock:
            state['sensor_diff'] = diff
            state['max_blow'] = max_blow
            state['blow_remaining'] = remaining
        
        time.sleep(0.05)
    
    print("측정 완료! 최대 입김:", max_blow)
    return max_blow

# ============================================
# 룰렛 회전
# ============================================
def spin_roulette(power):
    """power: 0.0 ~ 1.0"""
    print("🎰 룰렛 회전! 파워:", round(power, 2))
    
    with lock:
        state['game_state'] = GAME_SPINNING
        state['spin_count'] += 1
    
    # 회전 횟수 = 최소 20 ~ 최대 100 스텝
    total_steps = int(20 + power * 80)
    position = random.randint(0, cfg.NUM_LEDS - 1)
    accumulated_angle = 0
    
    for step in range(total_steps):
        position = (position + 1) % cfg.NUM_LEDS
        show_pointer(position)
        
        # 회전 각도 누적 (시각용)
        accumulated_angle += 36
        
        with lock:
            state['current_pos'] = position
            state['rotation_angle'] = accumulated_angle
        
        # 감속
        progress = step / total_steps
        delay = 0.04 + (progress ** 2.5) * 0.5
        time.sleep(delay)
    
    # 당첨!
    with lock:
        state['last_winner'] = position
        state['game_state'] = GAME_RESULT
    
    print("=" * 45)
    print("🎉 당첨!", position + 1, "번")
    print("📜 벌칙:", penalties[position])
    print("=" * 45)
    
    winner_celebration(position)
    show_pointer(position)

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
    print("\n=== 운명의 룰렛 (5초 입김 측정 버전) ===\n")
    
    ip = connect_wifi()
    if not ip:
        return
    
    _thread.start_new_thread(web_server_thread, ())
    time.sleep(1)
    
    baseline = calibrate()
    with lock:
        state['baseline'] = baseline
    
    show_idle()
    
    print("\n웹에서 START 버튼을 누르세요!")
    print("URL: http://" + ip + "\n")
    
    while True:
        with lock:
            start_trigger = state['start_trigger']
            current_game = state['game_state']
        
        # START 버튼 눌림!
        if start_trigger and current_game in (GAME_IDLE, GAME_RESULT):
            with lock:
                state['start_trigger'] = False
            
            # 1. 5초간 입김 측정
            max_blow = measure_blow(baseline)
            
            # 2. 입김 강도를 0~1로 정규화
            # 30000 이상이면 최대 (조절 가능)
            power = min(max_blow / 30000, 1.0)
            
            # 너무 약하면 최소 회전 보장
            if power < 0.1:
                power = 0.1
                print("입김이 약해서 최소로 회전!")
            
            # 3. 룰렛 회전
            spin_roulette(power)
            
            # 4. 결과 표시 후 5초 대기
            time.sleep(5)
            
            with lock:
                state['game_state'] = GAME_IDLE
            show_idle()
            print("\n다시 START 버튼을 눌러주세요!\n")
        
        # 평상시엔 센서값만 업데이트
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
