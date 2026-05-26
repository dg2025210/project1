from machine import Pin, ADC
from neopixel import NeoPixel
import network, socket, time, random, _thread
import wifi_config as cfg

# ===== 하드웨어 =====
TIMING = (280, 515, 515, 745)
led = NeoPixel(Pin(cfg.LED_PIN), cfg.NUM_LEDS, timing=TIMING)
mq2 = ADC(Pin(cfg.MQ2_PIN))

# ===== 색상 =====
COLORS = [(255,50,50),(255,140,0),(255,230,0),(150,255,0),(0,220,0),
          (0,230,180),(0,180,255),(60,80,255),(170,80,255),(255,60,200)]

# ===== 전역 상태 =====
# game: 0=대기, 1=측정, 2=회전, 3=결과
game_state = 0
current_pos = 0
last_winner = -1
sensor_diff = 0
spin_cnt = 0
trigger = False
blow_rem = 5
max_blow = 0
baseline = 0
penalties = ["노래 부르기", "댄스 30초", "개인기", "음료수 사오기",
             "셀카 10장", "닭다리 춤", "사랑한다 전화", "상품 사기"]

lock = _thread.allocate_lock()

# ===== LED 함수 =====
def led_clear():
    for i in range(cfg.NUM_LEDS):
        led[i] = (0, 0, 0)
    led.write()

def led_idle():
    n = len(penalties)
    per = cfg.NUM_LEDS // n
    extra = cfg.NUM_LEDS - per * n
    idx = 0
    for s in range(n):
        cnt = per + (1 if s < extra else 0)
        c = COLORS[s % 10]
        for _ in range(cnt):
            if idx < cfg.NUM_LEDS:
                led[idx] = (c[0]//12, c[1]//12, c[2]//12)
                idx += 1
    led.write()

def led_pointer(pos):
    n = len(penalties)
    per = cfg.NUM_LEDS // n
    extra = cfg.NUM_LEDS - per * n
    idx = 0
    for s in range(n):
        cnt = per + (1 if s < extra else 0)
        c = COLORS[s % 10]
        for _ in range(cnt):
            if idx < cfg.NUM_LEDS:
                led[idx] = c if s == pos else (c[0]//18, c[1]//18, c[2]//18)
                idx += 1
    led.write()

def led_blow(level):
    lit = int(cfg.NUM_LEDS * level)
    for i in range(cfg.NUM_LEDS):
        if i < lit:
            if level < 0.33: led[i] = (0, 200, 0)
            elif level < 0.66: led[i] = (200, 200, 0)
            else: led[i] = (255, 50, 0)
        else:
            led[i] = (5, 5, 20)
    led.write()

def hsv_rgb(h, s, v):
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

def led_celebrate(slot):
    c = COLORS[slot % 10]
    for _ in range(4):
        led_clear()
        time.sleep(0.12)
        for i in range(cfg.NUM_LEDS):
            led[i] = c
        led.write()
        time.sleep(0.12)
    for cy in range(20):
        for i in range(cfg.NUM_LEDS):
            led[i] = hsv_rgb((i*36 + cy*30) % 360, 1.0, 1.0)
        led.write()
        time.sleep(0.05)
    for i in range(cfg.NUM_LEDS):
        led[i] = c
    led.write()

# ===== WiFi =====
def connect_wifi():
    w = network.WLAN(network.STA_IF)
    w.active(True)
    if not w.isconnected():
        print("WiFi 연결 중...")
        w.connect(cfg.WIFI_SSID, cfg.WIFI_PASSWORD)
        for i in range(40):
            if w.isconnected(): break
            p = i % cfg.NUM_LEDS
            for j in range(cfg.NUM_LEDS):
                led[j] = (0, 50, 100) if j == p else (0, 5, 15)
            led.write()
            time.sleep(0.5)
    if not w.isconnected():
        print("WiFi 실패!")
        return None
    ip = w.ifconfig()[0]
    print("=" * 40)
    print("접속: http://" + ip)
    print("=" * 40)
    for i in range(cfg.NUM_LEDS):
        led[i] = (0, 50, 0)
    led.write()
    time.sleep(0.8)
    led_clear()
    return ip

# ===== HTML 페이지 =====
HTML_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>운명의 룰렛</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:sans-serif;background:radial-gradient(circle,#2d1b4e,#0f0524);color:#fff;padding:15px;min-height:100vh}
h1{text-align:center;font-size:26px;text-shadow:0 0 20px #f0f;margin-bottom:10px}
.box{max-width:400px;margin:10px auto;background:rgba(0,0,0,0.3);padding:12px;border-radius:10px}
.status{text-align:center;font-size:15px;color:#ffd700;font-weight:bold}
.wrap{position:relative;width:300px;height:300px;margin:15px auto}
.wheel{width:100%;height:100%;border-radius:50%;box-shadow:0 0 30px rgba(255,0,255,0.5);transition:transform 4s cubic-bezier(0.17,0.67,0.21,1)}
.wheel svg{width:100%;height:100%;display:block}
.ptr{position:absolute;top:-12px;left:50%;transform:translateX(-50%);width:0;height:0;border-left:18px solid transparent;border-right:18px solid transparent;border-top:30px solid #ffd700;filter:drop-shadow(0 0 8px #ffd700);z-index:10}
.ctr{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:100px;height:100px;background:radial-gradient(circle,#fff,#ffd700);border-radius:50%;box-shadow:0 0 20px #ffd700;z-index:5;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:bold;color:#333;cursor:pointer;text-align:center}
.ctr:active{transform:translate(-50%,-50%) scale(0.92)}
.ctr.cnt{font-size:55px;color:#ff0066}
.ctr.spn{font-size:20px;color:#f0f}
.msg{padding:18px;border-radius:12px;text-align:center;font-size:16px;font-weight:bold;line-height:1.4}
.msg.w{background:rgba(255,255,255,0.1);color:#ccc}
.msg.b{background:linear-gradient(45deg,#11998e,#38ef7d)}
.msg.s{background:linear-gradient(45deg,#0ff,#f0f)}
.msg.r{background:linear-gradient(135deg,#ff6b6b,#feca57);color:#333;font-size:18px}
.gas{height:25px;background:rgba(255,255,255,0.1);border-radius:12px;overflow:hidden;position:relative;display:none;margin-top:8px}
.gas.on{display:block}
.gf{height:100%;background:linear-gradient(90deg,#0f0,#ff0,#f00);width:0%;transition:width 0.15s}
.gm{position:absolute;left:0%;top:0;bottom:0;width:3px;background:#fff;transition:left 0.15s}
.btn{display:block;width:100%;padding:16px;font-size:18px;font-weight:bold;background:linear-gradient(45deg,#ff006e,#ff8a00,#ffce00);color:#fff;border:none;border-radius:30px;cursor:pointer;margin:10px 0}
.btn:active{transform:scale(0.97)}
.btn:disabled{background:#555;opacity:0.5}
.pen-row{background:rgba(255,255,255,0.06);padding:8px;margin:6px 0;border-radius:8px;display:flex;align-items:center;gap:8px}
.pen-row .dot{width:14px;height:14px;border-radius:50%;flex-shrink:0}
.pen-row input{flex:1;padding:8px;border:none;border-radius:5px;font-size:14px}
.pen-row .del{width:32px;height:32px;border:none;border-radius:50%;background:#e74c3c;color:#fff;font-weight:bold;cursor:pointer;font-size:18px;flex-shrink:0}
.pen-row .del:disabled{background:#555;opacity:0.4}
.add-btn{width:100%;padding:12px;font-size:18px;font-weight:bold;background:linear-gradient(45deg,#11998e,#38ef7d);color:#fff;border:none;border-radius:8px;cursor:pointer;margin-top:8px}
.add-btn:disabled{background:#555;opacity:0.5}
h2{font-size:16px;color:#ffd700;margin:10px 0;text-align:center}
.info{text-align:center;font-size:11px;color:#888;margin:8px 0}
</style></head><body>
<h1>🎰 운명의 룰렛</h1>
<div class="box"><div class="status" id="st">⏸️ 대기 중</div></div>
<div class="wrap">
<div class="ptr"></div>
<div class="wheel" id="wh"><svg id="sv" viewBox="-100 -100 200 200"></svg></div>
<div class="ctr" id="cc">🎰<br>START!</div>
</div>
<button class="btn" id="sb">🎰 START!</button>
<div class="box">
<div class="msg w" id="mg">🎯 START를 누르고<br>5초간 입김을 부세요!</div>
<div class="gas" id="ga"><div class="gf" id="gf"></div><div class="gm" id="gm"></div></div>
</div>
<div class="info" id="ci">총 0회</div>
<div class="box">
<h2>📝 벌칙 (<span id="np">0</span>/10)</h2>
<div id="pl"></div>
<button class="add-btn" id="ab">➕ 벌칙 추가</button>
</div>
<script>
var P=__P__;
var C=[[255,50,50],[255,140,0],[255,230,0],[150,255,0],[0,220,0],[0,230,180],[0,180,255],[60,80,255],[170,80,255],[255,60,200]];
var rot=0,lw=-1,spinning=false,si=null;

function colorOf(i){var c=C[i%10];return 'rgb('+c[0]+','+c[1]+','+c[2]+')';}

function drawWheel(){
  var s=document.getElementById('sv');s.innerHTML='';
  var N=P.length;if(N<1)return;
  var sa=360/N;
  for(var i=0;i<N;i++){
    var a1=(i*sa-90-sa/2)*Math.PI/180,a2=((i+1)*sa-90-sa/2)*Math.PI/180;
    var x1=Math.cos(a1)*95,y1=Math.sin(a1)*95,x2=Math.cos(a2)*95,y2=Math.sin(a2)*95;
    var la=sa>180?1:0;
    var c=C[i%10];
    var p=document.createElementNS('http://www.w3.org/2000/svg','path');
    if(N===1){
      p.setAttribute('d','M -95 0 a 95 95 0 1 0 190 0 a 95 95 0 1 0 -190 0');
    }else{
      p.setAttribute('d','M 0 0 L '+x1+' '+y1+' A 95 95 0 '+la+' 1 '+x2+' '+y2+' Z');
    }
    p.setAttribute('fill','rgb('+c[0]+','+c[1]+','+c[2]+')');
    p.setAttribute('stroke','#333');p.setAttribute('stroke-width','1');
    p.setAttribute('id','sl'+i);s.appendChild(p);
    var ma=(i*sa-90)*Math.PI/180,tr=N<=5?60:70;
    var t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x',N===1?0:Math.cos(ma)*tr);
    t.setAttribute('y',N===1?0:Math.sin(ma)*tr);
    t.setAttribute('text-anchor','middle');t.setAttribute('dominant-baseline','middle');
    t.setAttribute('fill','#fff');t.setAttribute('font-size',N<=5?'28':'20');
    t.setAttribute('font-weight','bold');t.textContent=i+1;s.appendChild(t);
  }
}

function drawPenList(){
  var l=document.getElementById('pl');l.innerHTML='';
  document.getElementById('np').textContent=P.length;
  for(var i=0;i<P.length;i++){
    (function(idx){
      var d=document.createElement('div');d.className='pen-row';
      var dot=document.createElement('div');dot.className='dot';dot.style.background=colorOf(idx);
      var inp=document.createElement('input');inp.value=P[idx];inp.maxLength=50;
      inp.addEventListener('input',function(){P[idx]=inp.value;savePenalties();});
      var del=document.createElement('button');del.className='del';del.textContent='×';
      del.disabled=(P.length<=2);
      del.addEventListener('click',function(){
        if(P.length<=2)return;
        P.splice(idx,1);
        savePenalties(function(){drawWheel();drawPenList();});
      });
      d.appendChild(dot);d.appendChild(inp);d.appendChild(del);
      l.appendChild(d);
    })(i);
  }
  document.getElementById('ab').disabled=(P.length>=10);
}

var saveT=null;
function savePenalties(cb){
  if(saveT)clearTimeout(saveT);
  saveT=setTimeout(function(){
    var b='n='+P.length;
    for(var i=0;i<P.length;i++){
      b+='&p'+i+'='+encodeURIComponent(P[i]);
    }
    fetch('/save',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:b})
      .then(function(){if(cb)cb();});
  },300);
}

function addPenalty(){
  if(P.length>=10)return;
  P.push('새 벌칙');
  savePenalties(function(){drawWheel();drawPenList();});
}

function startGame(){
  console.log('START 클릭');
  var b=document.getElementById('sb');
  b.disabled=true;
  fetch('/start').then(function(r){console.log('응답:',r.status);});
}

function highlight(i,on){
  var s=document.getElementById('sl'+i);if(!s)return;
  s.setAttribute('stroke',on?'#fff':'#333');
  s.setAttribute('stroke-width',on?'4':'1');
}
function clearHighlights(){for(var i=0;i<P.length;i++)highlight(i,false);}

function fastSpin(){
  var w=document.getElementById('wh');
  w.style.transition='transform 0.1s linear';
  si=setInterval(function(){rot+=72;w.style.transform='rotate('+rot+'deg)';},80);
}
function landAt(t){
  var w=document.getElementById('wh');
  if(si){clearInterval(si);si=null;}
  var sa=360/P.length,ta=-(t*sa),cm=rot%360,df=ta-cm;
  if(df>0)df-=360;
  var f=rot+3*360+df;
  w.style.transition='transform 3s cubic-bezier(0.17,0.67,0.21,1)';
  w.style.transform='rotate('+f+'deg)';rot=f;
}

function updateUI(){
  fetch('/status').then(function(r){return r.json();}).then(function(d){
    var st=document.getElementById('st'),cc=document.getElementById('cc'),
        mg=document.getElementById('mg'),ga=document.getElementById('ga'),
        ci=document.getElementById('ci'),sb=document.getElementById('sb');
    ci.textContent='총 '+d.cnt+'회';
    if(d.g===0){
      st.textContent='⏸️ 대기 중';
      cc.className='ctr';cc.innerHTML='🎰<br>START!';
      mg.className='msg w';mg.innerHTML='🎯 START를 누르고<br>5초간 입김을 부세요!';
      ga.classList.remove('on');clearHighlights();
      sb.disabled=false;sb.textContent='🎰 START!';
    }else if(d.g===1){
      st.textContent='💨 입김 측정 중!';
      cc.className='ctr cnt';cc.innerHTML=d.rem;
      mg.className='msg b';mg.innerHTML='💨 입김을 부세요!<br>최대: '+d.mx;
      ga.classList.add('on');
      document.getElementById('gf').style.width=Math.min(100,d.diff/200)+'%';
      document.getElementById('gm').style.left=Math.min(100,d.mx/200)+'%';
      sb.disabled=true;sb.textContent='💨 '+d.rem+'초...';
    }else if(d.g===2){
      st.textContent='🎰 회전 중!';
      cc.className='ctr spn';cc.innerHTML='SPIN!';
      mg.className='msg s';mg.innerHTML='🎰 두근두근...';
      ga.classList.remove('on');
      if(!spinning){spinning=true;lw=-1;fastSpin();}
      clearHighlights();highlight(d.pos,true);
      sb.disabled=true;sb.textContent='🎰 회전 중';
    }else if(d.g===3){
      st.textContent='✅ 결과!';
      cc.className='ctr';cc.innerHTML='🔄<br>다시!';
      mg.className='msg r';mg.innerHTML='🎉 '+(d.win+1)+'번 당첨!<br>📜 '+P[d.win];
      ga.classList.remove('on');
      if(lw!==d.win){
        lw=d.win;
        if(spinning){spinning=false;landAt(d.win);}
        setTimeout(function(){clearHighlights();highlight(d.win,true);},3000);
      }
      sb.disabled=false;sb.textContent='🔄 다시!';
    }
  }).catch(function(e){console.error(e);});
}

window.addEventListener('load',function(){
  console.log('로드 완료');
  drawWheel();drawPenList();
  document.getElementById('cc').addEventListener('click',startGame);
  document.getElementById('sb').addEventListener('click',startGame);
  document.getElementById('ab').addEventListener('click',addPenalty);
  setInterval(updateUI,300);updateUI();
});
</script></body></html>"""

def make_page():
    global penalties
    with lock:
        pen_list = list(penalties)
    items = []
    for p in pen_list:
        safe = p.replace('\\', '\\\\').replace('"', '\\"')
        items.append('"' + safe + '"')
    pen_js = "[" + ",".join(items) + "]"
    return HTML_PAGE.replace("__P__", pen_js)

# ===== URL 디코딩 =====
def url_decode(s):
    r = bytearray()
    i = 0
    while i < len(s):
        if s[i] == '%':
            try:
                r.append(int(s[i+1:i+3], 16))
                i += 3
            except:
                i += 1
        elif s[i] == '+':
            r.append(0x20)
            i += 1
        else:
            r.append(ord(s[i]))
            i += 1
    try:
        return r.decode('utf-8')
    except:
        return r.decode('utf-8', 'ignore')

def parse_post(body):
    d = {}
    for p in body.split('&'):
        if '=' in p:
            k, v = p.split('=', 1)
            d[k] = url_decode(v)
    return d

# ===== 웹 서버 =====
def web_server():
    global penalties, trigger, last_winner, game_state
    
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(3)
    print("🌐 웹 서버 시작!")
    
    while True:
        try:
            cl, _ = s.accept()
            cl.settimeout(3.0)
            req = cl.recv(2048).decode('utf-8')
            first_line = req.split('\r\n')[0]
            parts = first_line.split(' ')
            method = parts[0] if len(parts) > 0 else ''
            path = parts[1] if len(parts) > 1 else '/'
            
            # 1. /start - 게임 시작
            if path.startswith('/start'):
                print(">>> START 요청 받음!")
                with lock:
                    print("   현재 게임 상태:", game_state)
                    if game_state == 0 or game_state == 3:
                        trigger = True
                        print("   ✅ 트리거 설정 완료!")
                    else:
                        print("   ⚠️ 진행 중이라 무시")
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nOK')
            
            # 2. /status - 상태 JSON
            elif path.startswith('/status'):
                with lock:
                    j = '{"g":%d,"pos":%d,"win":%d,"diff":%d,"mx":%d,"rem":%d,"cnt":%d}' % (
                        game_state, current_pos, last_winner, sensor_diff,
                        max_blow, blow_rem, spin_cnt)
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n')
                cl.send(j)
            
            # 3. /save - 벌칙 저장
            elif method == 'POST' and '/save' in path:
                if '\r\n\r\n' in req:
                    body = req.split('\r\n\r\n', 1)[1]
                    data = parse_post(body)
                    try:
                        n = int(data.get('n', '0'))
                    except:
                        n = 0
                    if 2 <= n <= 10:
                        new_pen = []
                        for i in range(n):
                            k = 'p' + str(i)
                            val = data.get(k, '벌칙').strip()
                            if not val:
                                val = '벌칙'
                            new_pen.append(val)
                        with lock:
                            penalties = new_pen
                            last_winner = -1
                            if game_state == 3:
                                game_state = 0
                        print("📝 벌칙 저장됨! 개수:", n)
                cl.send('HTTP/1.0 200 OK\r\n\r\nOK')
            
            # 4. 메인 페이지
            else:
                html = make_page()
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n')
                chunk = 1024
                for i in range(0, len(html), chunk):
                    cl.send(html[i:i+chunk])
            
            cl.close()
        except Exception as e:
            print("서버 에러:", e)
            try:
                cl.close()
            except:
                pass

# ===== 게임 함수 =====
def measure_blow():
    global game_state, max_blow, blow_rem, sensor_diff
    print("\n💨 입김 측정 시작! (5초)")
    
    with lock:
        game_state = 1
        max_blow = 0
        blow_rem = 5
    
    mx = 0
    start_time = time.ticks_ms()
    
    while True:
        elapsed = time.ticks_diff(time.ticks_ms(), start_time)
        remaining = 5 - (elapsed // 1000)
        if elapsed >= 5000:
            break
        
        v = mq2.read_u16()
        diff = abs(v - baseline)
        if diff > mx:
            mx = diff
        
        led_blow(min(diff / 20000, 1.0))
        
        with lock:
            sensor_diff = diff
            max_blow = mx
            blow_rem = max(0, remaining)
        
        time.sleep(0.05)
    
    print("   최대 변화량:", mx)
    return mx

def do_spin(power):
    global game_state, current_pos, last_winner, spin_cnt
    
    with lock:
        n = len(penalties)
    
    print("🎰 룰렛 회전! 파워:", round(power, 2))
    
    with lock:
        game_state = 2
        spin_cnt += 1
    
    steps = int(15 + power * 80)
    pos = random.randint(0, n - 1)
    
    for st in range(steps):
        pos = (pos + 1) % n
        led_pointer(pos)
        with lock:
            current_pos = pos
        progress = st / steps
        time.sleep(0.04 + (progress ** 2.5) * 0.5)
    
    with lock:
        last_winner = pos
        game_state = 3
        winning = penalties[pos]
    
    print("🎉 당첨!", pos + 1, "번 -", winning)
    led_celebrate(pos)
    led_pointer(pos)

def calibrate():
    print("🌬️ MQ-2 예열 중...")
    samples = []
    for i in range(20):
        samples.append(mq2.read_u16())
        for j in range(cfg.NUM_LEDS):
            led[j] = hsv_rgb((i*18 + j*36) % 360, 1.0, 0.3)
        led.write()
        time.sleep(0.3)
    b = sum(samples) // len(samples)
    print("   베이스라인:", b)
    return b

# ===== 메인 =====
def main():
    global baseline, trigger, game_state, sensor_diff
    
    print("\n" + "=" * 40)
    print("🎰 운명의 룰렛 시작!")
    print("=" * 40 + "\n")
    
    ip = connect_wifi()
    if not ip:
        return
    
    _thread.start_new_thread(web_server, ())
    time.sleep(1)
    
    baseline = calibrate()
    led_idle()
    
    print("\n✅ 준비 완료! 브라우저에서 START 버튼을 누르세요!")
    print("   URL: http://" + ip + "\n")
    
    while True:
        # 트리거 확인
        with lock:
            trig = trigger
            gs = game_state
        
        if trig:
            print("\n>>> 메인 루프: 트리거 감지! 상태:", gs)
            with lock:
                trigger = False
            
            if gs == 0 or gs == 3:
                # 게임 시작!
                mx = measure_blow()
                power = min(mx / 20000, 1.0)
                if power < 0.1:
                    power = 0.1
                
                do_spin(power)
                
                # 결과 5초 표시
                time.sleep(5)
                
                with lock:
                    game_state = 0
                led_idle()
                print(">>> 대기 모드로 전환\n")
        else:
            # 평상시 센서값 갱신
            v = mq2.read_u16()
            with lock:
                sensor_diff = abs(v - baseline)
            time.sleep(0.1)

# ===== 실행 =====
try:
    main()
except KeyboardInterrupt:
    led_clear()
    print("\n종료!")
except Exception as e:
    led_clear()
    print("오류:", e)
    import sys
    sys.print_exception(e)
