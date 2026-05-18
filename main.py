from machine import Pin, ADC
from neopixel import NeoPixel
import network
import socket
import time
import random
import _thread
import wifi_config as cfg

# ============================================
# WS2813 Mini 전용 타이밍 ⚠️
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

# 기본 벌칙
penalties = [
    "🎤 노래 한 곡 부르기!",
    "💃 30초 댄스 타임!",
    "🤣 개인기 보여주기",
    "🍵 음료수 사오기",
    "📸 웃긴 셀카 10장 찍기",
    "🐔 닭다리 춤 추기",
    "📞 친구에게 사랑한다 전화",
    "🎁 다음 게임 상품 사기",
    "🙊 1분간 말하지 않기",
    "🏃 팔굽혀펴기 10개"
]

# 공유 상태
state = {
    'spinning': False,
    'current_pos': 0,
    'last_winner': -1,
    'gas_value': 0,
    'sensor_diff': 0,
    'spin_count': 0,
    'spin_trigger': False,  # 웹에서 트리거
    'spin_power': 0.5,      # 회전 강도
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
# WiFi 연결 (Station 모드)
# ============================================
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    if not wlan.isconnected():
        print("📡 WiFi 연결 중...")
        print(f"   SSID: {cfg.WIFI_SSID}")
        wlan.connect(cfg.WIFI_SSID, cfg.WIFI_PASSWORD)
        
        # 연결 대기 중 LED 표시
        timeout = 20
        for i in range(timeout * 2):
            if wlan.isconnected():
                break
            # 파란색 회전 효과
            pos = i % cfg.NUM_LEDS
            for j in range(cfg.NUM_LEDS):
                if j == pos:
                    led[j] = (0, 50, 100)
                else:
                    led[j] = (0, 5, 15)
            led.write()
            time.sleep(0.5)
        
        if not wlan.isconnected():
            print("❌ WiFi 연결 실패!")
            # 빨간색 깜빡임
            for _ in range(3):
                for i in range(cfg.NUM_LEDS):
                    led[i] = (100, 0, 0)
                led.write()
                time.sleep(0.3)
                clear()
                time.sleep(0.3)
            return None
    
    ip = wlan.ifconfig()[0]
    print("=" * 45)
    print("✅ WiFi 연결 성공!")
    print(f"   IP: {ip}")
    print(f"📱 http://{ip} 에 접속하세요!")
    print("=" * 45)
    
    # 성공 표시 (초록색 한 번)
    for i in range(cfg.NUM_LEDS):
        led[i] = (0, 50, 0)
    led.write()
    time.sleep(0.8)
    clear()
    
    return ip

# ============================================
# 웹페이지 (룰렛이 메인!) 🎰
# ============================================
def generate_main_page():
    # 색상 리스트를 JS 문자열로
    colors_js = "[" + ",".join([f"[{c[0]},{c[1]},{c[2]}]" for c in SLOT_COLORS]) + "]"
    
    # 벌칙을 JS 문자열로
    penalties_js = "[" + ",".join([f'"{p}"' for p in penalties]) + "]"
    
    # 벌칙 입력 폼
    rows = ""
    for i, color in enumerate(SLOT_COLORS):
        hex_color = '#{:02x}{:02x}{:02x}'.format(color[0], color[1], color[2])
        rows += f'''
        <div class="slot" style="border-left: 6px solid {hex_color};">
            <label>{i+1}번 칸</label>
            <input type="text" name="p{i}" value="{penalties[i]}" maxlength="50">
        </div>
        '''
    
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🎰 운명의 룰렛</title>
<style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
        font-family: 'Apple SD Gothic Neo', sans-serif;
        background: radial-gradient(circle at center, #2d1b4e, #0f0524);
        color: white;
        padding: 15px;
        min-height: 100vh;
    }}
    h1 {{
        text-align: center;
        font-size: 32px;
        text-shadow: 0 0 20px #ff00ff, 0 0 40px #ff00ff;
        margin-bottom: 5px;
        animation: glow 2s infinite alternate;
    }}
    @keyframes glow {{
        from {{ text-shadow: 0 0 10px #ff00ff; }}
        to {{ text-shadow: 0 0 30px #ff00ff, 0 0 50px #ff00ff; }}
    }}
    .subtitle {{
        text-align: center;
        color: #aaa;
        font-size: 13px;
        margin-bottom: 20px;
    }}
    
    /* ============= 메인 룰렛 ============= */
    .roulette-container {{
        position: relative;
        width: 90vw;
        max-width: 400px;
        aspect-ratio: 1;
        margin: 20px auto;
    }}
    
    .roulette-wheel {{
        width: 100%;
        height: 100%;
        border-radius: 50%;
        position: relative;
        transition: transform 4s cubic-bezier(0.17, 0.67, 0.21, 1);
        box-shadow: 
            0 0 40px rgba(255,0,255,0.5),
            inset 0 0 30px rgba(0,0,0,0.5);
    }}
    
    .roulette-wheel svg {{
        width: 100%;
        height: 100%;
    }}
    
    /* 룰렛 포인터 (위쪽 화살표) */
    .pointer {{
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
    }}
    
    /* 중심 원 */
    .center-circle {{
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
    }}
    
    /* ============= START 버튼 ============= */
    .start-btn {{
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
        text-shadow: 0 2px 5px rgba(0,0,0,0.3);
    }}
    .start-btn:active {{ transform: scale(0.95); }}
    .start-btn:disabled {{
        background: #555;
        cursor: not-allowed;
        opacity: 0.5;
    }}
    
    /* ============= 결과 박스 ============= */
    .winner-box {{
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
        box-shadow: 0 8px 30px rgba(255,107,107,0.5);
        min-height: 80px;
        display: flex;
        align-items: center;
        justify-content: center;
    }}
    .winner-box.waiting {{
        background: rgba(255,255,255,0.1);
        color: #aaa;
    }}
    .winner-box.spinning {{
        background: linear-gradient(45deg, #00f5ff, #ff00ff);
        color: white;
        animation: pulse 0.6s infinite;
    }}
    @keyframes pulse {{
        0%, 100% {{ transform: scale(1); }}
        50% {{ transform: scale(1.04); }}
    }}
    
    /* ============= 상태 바 ============= */
    .status-bar {{
        max-width: 400px;
        margin: 15px auto;
        padding: 12px 18px;
        background: rgba(0,0,0,0.4);
        border-radius: 12px;
        border: 1px solid #444;
    }}
    .status-row {{
        display: flex;
        justify-content: space-between;
        font-size: 13px;
        margin: 4px 0;
    }}
    .status-label {{ color: #888; }}
    .status-value {{ color: #00ffff; font-weight: bold; }}
    
    .gas-meter {{
        height: 8px;
        background: rgba(255,255,255,0.1);
        border-radius: 4px;
        overflow: hidden;
        margin-top: 8px;
    }}
    .gas-fill {{
        height: 100%;
        background: linear-gradient(90deg, #00ff00, #ffff00, #ff0000);
        width: 0%;
        transition: width 0.2s;
    }}
    
    /* ============= 벌칙 입력 ============= */
    .penalties-section {{
        max-width: 400px;
        margin: 30px auto 0;
    }}
    h2 {{
        font-size: 18px;
        color: #ffd700;
        margin-bottom: 10px;
        text-align: center;
    }}
    .slot {{
        background: rgba(255,255,255,0.06);
        padding: 10px 12px;
        margin: 8px 0;
        border-radius: 8px;
    }}
    .slot label {{
        display: block;
        font-weight: bold;
        margin-bottom: 4px;
        color: #ffd700;
        font-size: 12px;
    }}
    .slot input {{
        width: 100%;
        padding: 8px;
        font-size: 14px;
        border: none;
        border-radius: 5px;
    }}
    .save-btn {{
        width: 100%;
        padding: 14px;
        font-size: 16px;
        font-weight: bold;
        background: linear-gradient(45deg, #667eea, #764ba2);
        color: white;
        border: none;
        border-radius: 10px;
        cursor: pointer;
        margin-top: 12px;
    }}
    .save-btn:active {{ transform: scale(0.97); }}
    
    .hint {{
        text-align: center;
        color: #888;
        font-size: 12px;
        margin: 15px 0;
        line-height: 1.6;
    }}
    .live-dot {{
        display: inline-block;
        width: 8px;
        height: 8px;
        background: #ff0000;
        border-radius: 50%;
        animation: blink 1s infinite;
    }}
    @keyframes blink {{
        50% {{ opacity: 0.3; }}
    }}
</style>
</head>
<body>
    <h1>🎰 운명의 룰렛 🎰</h1>
    <p class="subtitle"><span class="live-dot"></span> LIVE | MQ-2 + WS2813</p>
    
    <!-- 메인 룰렛! -->
    <div class="roulette-container">
        <div class="pointer"></div>
        <div class="roulette-wheel" id="wheel">
            <svg viewBox="-100 -100 200 200" id="wheelSvg"></svg>
        </div>
        <div class="center-circle">🎯</div>
    </div>
    
    <!-- 결과 -->
    <div class="winner-box waiting" id="winnerBox">
        👻 START 버튼을 누르거나<br>MQ-2에 입김을 불어보세요!
    </div>
    
    <!-- START 버튼 -->
    <button class="start-btn" id="startBtn" onclick="triggerSpin()">
        🎰 룰렛 돌리기!
    </button>
    
    <!-- 상태 -->
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
    
    <!-- 벌칙 설정 -->
    <div class="penalties-section">
        <h2>📝 벌칙 설정</h2>
        <form action="/save" method="POST">
            {rows}
            <button type="submit" class="save-btn">💾 저장하기</button>
        </form>
    </div>

<script>
    const colors = {colors_js};
    const penalties = {penalties_js};
    const NUM_SLOTS = 10;
    
    // ===== 룰렛 SVG 생성 =====
    const svg = document.getElementById('wheelSvg');
    const sliceAngle = 360 / NUM_SLOTS;
    
    for (let i = 0; i < NUM_SLOTS; i++) {{
        // 각 슬라이스를 path로 그리기
        const startAngle = (i * sliceAngle - 90 - sliceAngle/2) * Math.PI / 180;
        const endAngle = ((i+1) * sliceAngle - 90 - sliceAngle/2) * Math.PI / 180;
        
        const x1 = Math.cos(startAngle) * 95;
        const y1 = Math.sin(startAngle) * 95;
        const x2 = Math.cos(endAngle) * 95;
        const y2 = Math.sin(endAngle) * 95;
        
        const c = colors[i];
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', `M 0 0 L ${{x1}} ${{y1}} A 95 95 0 0 1 ${{x2}} ${{y2}} Z`);
        path.setAttribute('fill', `rgb(${{c[0]}},${{c[1]}},${{c[2]}})`);
        path.setAttribute('stroke', '#fff');
        path.setAttribute('stroke-width', '1');
        svg.appendChild(path);
        
        // 숫자 텍스트
        const midAngle = (i * sliceAngle - 90) * Math.PI / 180;
        const tx = Math.cos(midAngle) * 65;
        const ty = Math.sin(midAngle) * 65;
        const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        text.setAttribute('x', tx);
        text.setAttribute('y', ty);
        text.setAttribute('text-anchor', 'middle');
        text.setAttribute('dominant-baseline', 'middle');
        text.setAttribute('fill', 'white');
        text.setAttribute('font-size', '18');
        text.setAttribute('font-weight', 'bold');
        text.setAttribute('style', 'text-shadow: 0 0 5px rgba(0,0,0,0.8);');
        text.textContent = (i + 1);
        svg.appendChild(text);
    }}
    
    // ===== 룰렛 회전 (시각) =====
    const wheel = document.getElementById('wheel');
    let currentRotation = 0;
    let isSpinning = false;
    let lastWinnerShown = -1;
    
    function spinWheelToPosition(targetPos, duration) {{
        // targetPos: 0~9, duration: 초
        // 포인터는 위쪽(12시 방향), 칸 0은 위쪽에서 시작
        // 멈출 각도: targetPos가 위에 오도록
        const targetAngle = -(targetPos * 36);  // 음수는 시계방향
        
        // 추가 회전(5바퀴 이상)
        const extraRotations = 5 + Math.floor(duration);
        const finalRotation = currentRotation + (extraRotations * 360) + 
                              (targetAngle - (currentRotation % 360));
        
        wheel.style.transition = `transform ${{duration}}s cubic-bezier(0.17, 0.67, 0.21, 1)`;
        wheel.style.transform = `rotate(${{finalRotation}}deg)`;
        currentRotation = finalRotation;
    }}
    
    // ===== START 버튼 =====
    async function triggerSpin() {{
        if (isSpinning) return;
        await fetch('/spin');
    }}
    
    // ===== 실시간 상태 폴링 =====
    async function updateStatus() {{
        try {{
            const res = await fetch('/status');
            const data = await res.json();
            
            // 상태 표시
            document.getElementById('status').textContent = 
                data.spinning ? '🎰 회전 중!' : '⏸️ 대기 중';
            document.getElementById('spinCount').textContent = data.spin_count;
            document.getElementById('diffValue').textContent = data.sensor_diff;
            
            // 가스 미터
            const pct = Math.min(100, (data.sensor_diff / 30000) * 100);
            document.getElementById('gasFill').style.width = pct + '%';
            
            // 버튼 활성화
            document.getElementById('startBtn').disabled = data.spinning;
            
            // 회전 시작 감지
            if (data.spinning && !isSpinning) {{
                isSpinning = true;
                lastWinnerShown = -1;
                
                // 룰렛 회전 시작! (서버에서 결과 받기 전에 미리 돌리기)
                document.getElementById('winnerBox').className = 'winner-box spinning';
                document.getElementById('winnerBox').innerHTML = '🎰 회전 중...<br>두근두근...';
                
                // 일단 빠르게 계속 도는 애니메이션
                wheel.style.transition = 'transform 0.1s linear';
                let fastSpin = setInterval(() => {{
                    currentRotation += 60;
                    wheel.style.transform = `rotate(${{currentRotation}}deg)`;
                }}, 50);
                wheel._fastSpin = fastSpin;
            }}
            
            // 회전 종료 감지
            if (!data.spinning && isSpinning && data.last_winner >= 0) {{
                isSpinning = false;
                
                // 빠른 회전 멈추고 최종 위치로
                if (wheel._fastSpin) {{
                    clearInterval(wheel._fastSpin);
                    wheel._fastSpin = null;
                }}
                
                // 부드럽게 결과 위치로 이동
                spinWheelToPosition(data.last_winner, 3);
                
                // 3초 후 결과 표시
                setTimeout(() => {{
                    if (lastWinnerShown !== data.last_winner) {{
                        document.getElementById('winnerBox').className = 'winner-box';
                        document.getElementById('winnerBox').innerHTML = 
                            `🎉 ${{data.last_winner + 1}}번 당첨! 🎉<br>📜 ${{penalties[data.last_winner]}}`;
                        lastWinnerShown = data.last_winner;
                        
                        // 폭죽 효과 (간단한 깜빡임)
                        document.body.style.background = 'radial-gradient(circle, #ff00ff, #0f0524)';
                        setTimeout(() => {{
                            document.body.style.background = 'radial-gradient(circle at center, #2d1b4e, #0f0524)';
                        }}, 500);
                    }}
                }}, 3000);
            }}
            
        }} catch (e) {{
            console.error(e);
        }}
    }}
    
    setInterval(updateStatus, 300);
    updateStatus();
</script>
</body>
</html>"""
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
    print("🌐 웹 서버 시작!")
    
    while True:
        try:
            cl, addr = s.accept()
            cl.settimeout(3.0)
            request = cl.recv(2048).decode('utf-8')
            first_line = request.split('\r\n')[0]
            
            # 실시간 상태 API
            if 'GET /status' in first_line:
                with lock:
                    json_data = (
                        '{'
                        f'"spinning":{str(state["spinning"]).lower()},'
                        f'"current_pos":{state["current_pos"]},'
                        f'"last_winner":{state["last_winner"]},'
                        f'"sensor_diff":{state["sensor_diff"]},'
                        f'"spin_count":{state["spin_count"]}'
                        '}'
                    )
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n')
                cl.send(json_data)
            
            # 웹 버튼으로 룰렛 트리거
            elif 'GET /spin' in first_line:
                with lock:
                    if not state['spinning']:
                        state['spin_trigger'] = True
                        state['spin_power'] = 0.7  # 웹 버튼은 기본 강도
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nOK')
            
            # 벌칙 저장
            elif 'POST /save' in first_line:
                if '\r\n\r\n' in request:
                    body = request.split('\r\n\r\n', 1)[1]
                    data = parse_post(body)
                    for i in range(cfg.NUM_LEDS):
                        key = f'p{i}'
                        if key in data and data[key].strip():
                            penalties[i] = data[key].strip()
                    print("✅ 벌칙 업데이트!")
                cl.send('HTTP/1.0 303 See Other\r\nLocation: /\r\n\r\n')
            
            # 메인 페이지
            else:
                html = generate_main_page()
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n')
                cl.send(html)
            
            cl.close()
        except Exception as e:
            try:
                cl.close()
            except:
                pass

# ============================================
# 룰렛 실행 (메인 스레드)
# ============================================
def spin_roulette(power):
    print(f"\n🎰 룰렛 회전! (파워: {power:.2f})")
    
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
    
    # 당첨!
    with lock:
        state['last_winner'] = position
    
    print("=" * 45)
    print(f"🎉 당첨! {position + 1}번")
    print(f"📜 {penalties[position]}")
    print("=" * 45)
    
    winner_celebration(position)
    show_pointer(position)
    
    with lock:
        state['spinning'] = False

# ============================================
# 센서 캘리브레이션
# ============================================
def calibrate():
    print("\n🌬️  MQ-2 센서 예열 중...")
    samples = []
    for i in range(20):
        samples.append(mq2.read_u16())
        for j in range(cfg.NUM_LEDS):
            hue = (i * 18 + j * 36) % 360
            led[j] = hsv_to_rgb(hue, 1.0, 0.3)
        led.write()
        time.sleep(0.3)
    baseline = sum(samples) // len(samples)
    print(f"✅ 베이스라인: {baseline}\n")
    return baseline

# ============================================
# 메인
# ============================================
def main():
    print("\n" + "🎮" * 22)
    print("  운명의 룰렛 - 웹 메인 버전")
    print("🎮" * 22 + "\n")
    
    # WiFi 연결
    ip = connect_wifi()
    if not ip:
        print("WiFi 없이는 진행할 수 없어요!")
        return
    
    # 웹서버를 Core 1에서 실행
    _thread.start_new_thread(web_server_thread, ())
    time.sleep(1)
    
    # 센서 예열
    baseline = calibrate()
    show_idle()
    
    print(f"💨 입김을 불거나 웹에서 버튼을 누르세요!")
    print(f"📱 http://{ip}\n")
    
    while True:
        gas_value = mq2.read_u16()
        diff = gas_value - baseline
        
        with lock:
            state['gas_value'] = gas_value
            state['sensor_diff'] = max(0, diff)
            web_trigger = state['spin_trigger']
            web_power = state['spin_power']
            is_spinning = state['spinning']
        
        # 웹 버튼 트리거
        if web_trigger and not is_spinning:
            with lock:
                state['spin_trigger'] = False
            spin_roulette(web_power)
            time.sleep(cfg.COOLDOWN_TIME)
        
        # 입김 감지
        elif diff > cfg.TRIGGER_THRESHOLD and not is_spinning:
            print(f"💨 입김 감지! (변화량: {diff})")
            
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
            
            print(f"⏸️  {cfg.COOLDOWN_TIME}초 후 재도전\n")
            time.sleep(cfg.COOLDOWN_TIME)
        
        time.sleep(0.05)

# 실행
try:
    main()
except KeyboardInterrupt:
    clear()
    print("\n게임 종료!")
except Exception as e:
    clear()
    print("오류:", e)
    import sys
    sys.print_exception(e)
