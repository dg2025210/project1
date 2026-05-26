from machine import Pin, ADC
from neopixel import NeoPixel
import network, socket, time, random, math, _thread
import wifi_config as cfg

# WS2813 Mini 타이밍
TIMING = (280, 515, 515, 745)
led = NeoPixel(Pin(cfg.LED_PIN), cfg.NUM_LEDS, timing=TIMING)
mq2 = ADC(Pin(cfg.MQ2_PIN))

COLORS = [(255,50,50),(255,140,0),(255,230,0),(150,255,0),(0,220,0),
          (0,230,180),(0,180,255),(60,80,255),(170,80,255),(255,60,200)]

DEFAULT_PENALTIES = ["노래 부르기","댄스 30초","개인기","음료수 사오기",
                     "셀카 10장","닭다리 춤","사랑한다 전화","상품 사기",
                     "1분 침묵","팔굽혀펴기 10개"]

# 상태 (0:대기 1:측정 2:회전 3:결과)
S = {'g':0,'pos':0,'win':-1,'diff':0,'cnt':0,'trig':False,
     'rem':5,'mx':0,'base':0,'n':8,'pen':list(DEFAULT_PENALTIES)}
lk = _thread.allocate_lock()

# ============ LED ============
def clr():
    for i in range(cfg.NUM_LEDS): led[i]=(0,0,0)
    led.write()

def show_idle():
    with lk: n = S['n']
    per = cfg.NUM_LEDS // n
    ex = cfg.NUM_LEDS - per*n
    idx = 0
    for s in range(n):
        cnt = per + (1 if s < ex else 0)
        c = COLORS[s]
        for _ in range(cnt):
            if idx < cfg.NUM_LEDS:
                led[idx] = (c[0]//12, c[1]//12, c[2]//12)
                idx += 1
    led.write()

def show_pointer(p):
    with lk: n = S['n']
    per = cfg.NUM_LEDS // n
    ex = cfg.NUM_LEDS - per*n
    idx = 0
    for s in range(n):
        cnt = per + (1 if s < ex else 0)
        c = COLORS[s]
        for _ in range(cnt):
            if idx < cfg.NUM_LEDS:
                led[idx] = c if s==p else (c[0]//18, c[1]//18, c[2]//18)
                idx += 1
    led.write()

def show_blow(lv):
    nl = int(cfg.NUM_LEDS * lv)
    for i in range(cfg.NUM_LEDS):
        if i < nl:
            led[i] = (0,200,0) if lv<0.33 else (200,200,0) if lv<0.66 else (255,50,0)
        else:
            led[i] = (5,5,20)
    led.write()

def hsv(h,s,v):
    c=v*s; x=c*(1-abs((h/60)%2-1)); m=v-c
    if h<60: r,g,b=c,x,0
    elif h<120: r,g,b=x,c,0
    elif h<180: r,g,b=0,c,x
    elif h<240: r,g,b=0,x,c
    elif h<300: r,g,b=x,0,c
    else: r,g,b=c,0,x
    return (int((r+m)*255),int((g+m)*255),int((b+m)*255))

def celebrate(slot):
    c = COLORS[slot]
    for _ in range(4):
        clr(); time.sleep(0.12)
        for i in range(cfg.NUM_LEDS): led[i] = c
        led.write(); time.sleep(0.12)
    for cy in range(20):
        for i in range(cfg.NUM_LEDS):
            led[i] = hsv((i*36+cy*30)%360, 1.0, 1.0)
        led.write(); time.sleep(0.05)
    for i in range(cfg.NUM_LEDS): led[i] = c
    led.write()

# ============ WiFi ============
def wifi():
    w = network.WLAN(network.STA_IF)
    w.active(True)
    if not w.isconnected():
        print("WiFi 연결 중...")
        w.connect(cfg.WIFI_SSID, cfg.WIFI_PASSWORD)
        for i in range(40):
            if w.isconnected(): break
            p = i % cfg.NUM_LEDS
            for j in range(cfg.NUM_LEDS):
                led[j] = (0,50,100) if j==p else (0,5,15)
            led.write()
            time.sleep(0.5)
    if not w.isconnected():
        print("WiFi 실패!")
        return None
    ip = w.ifconfig()[0]
    print("="*45)
    print("접속: http://" + ip)
    print("="*45)
    for i in range(cfg.NUM_LEDS): led[i] = (0,50,0)
    led.write(); time.sleep(0.8); clr()
    return ip

# ============ HTML ============
PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>운명의 룰렛</title><style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:sans-serif;background:radial-gradient(circle,#2d1b4e,#0f0524);color:#fff;padding:15px;min-height:100vh}
h1{text-align:center;font-size:26px;text-shadow:0 0 20px #f0f;margin-bottom:10px}
.box{max-width:400px;margin:10px auto;background:rgba(0,0,0,0.3);padding:12px;border-radius:10px}
.status{text-align:center;font-size:15px;color:#ffd700;font-weight:bold}
.ctrl{display:flex;align-items:center;justify-content:center;gap:10px;margin:10px 0}
.ctrl button{width:40px;height:40px;border:none;border-radius:50%;font-size:20px;font-weight:bold;background:#667eea;color:#fff;cursor:pointer}
.ctrl button:disabled{background:#555;opacity:0.5}
.ctrl span{font-size:22px;font-weight:bold;color:#ffd700;min-width:60px;text-align:center}
.wrap{position:relative;width:300px;height:300px;margin:15px auto}
.wheel{width:100%;height:100%;border-radius:50%;box-shadow:0 0 30px rgba(255,0,255,0.5);transition:transform 4s cubic-bezier(0.17,0.67,0.21,1)}
.wheel svg{width:100%;height:100%;display:block}
.ptr{position:absolute;top:-12px;left:50%;transform:translateX(-50%);width:0;height:0;border-left:18px solid transparent;border-right:18px solid transparent;border-top:30px solid #ffd700;filter:drop-shadow(0 0 8px #ffd700);z-index:10}
.ctr{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:100px;height:100px;background:radial-gradient(circle,#fff,#ffd700);border-radius:50%;box-shadow:0 0 20px #ffd700;z-index:5;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:bold;color:#333;cursor:pointer;text-align:center;user-select:none}
.ctr:active{transform:translate(-50%,-50%) scale(0.92)}
.ctr.cnt{font-size:55px;color:#ff0066;background:radial-gradient(circle,#fff,#ff99cc)}
.ctr.spn{font-size:20px;color:#f0f;animation:pls 0.5s infinite}
@keyframes pls{50%{transform:translate(-50%,-50%) scale(1.1)}}
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
.pen{background:rgba(255,255,255,0.06);padding:10px;margin:6px 0;border-radius:8px;display:flex;align-items:center;gap:8px}
.pen .dot{width:14px;height:14px;border-radius:50%;flex-shrink:0}
.pen input{flex:1;padding:8px;border:none;border-radius:5px;font-size:14px}
.save{width:100%;padding:12px;font-size:15px;font-weight:bold;background:linear-gradient(45deg,#667eea,#764ba2);color:#fff;border:none;border-radius:8px;cursor:pointer;margin-top:8px}
h2{font-size:16px;color:#ffd700;margin:10px 0;text-align:center}
.cnt-info{text-align:center;font-size:11px;color:#888;margin:8px 0}
.dot-live{display:inline-block;width:8px;height:8px;background:#f00;border-radius:50%;animation:blk 1s infinite}
@keyframes blk{50%{opacity:0.3}}
</style></head><body>
<h1>🎰 운명의 룰렛</h1>
<div class="box">
<div class="status" id="st">⏸️ 대기 중</div>
<div class="ctrl">
<span style="color:#aaa;font-size:13px">벌칙 개수:</span>
<button id="bm">−</button>
<span id="nn">8</span>
<button id="bp">+</button>
</div>
</div>
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
<div class="cnt-info" id="ci"><span class="dot-live"></span> 총 0회</div>
<div class="box">
<h2>📝 벌칙 설정</h2>
<form action="/save" method="POST" id="pf"></form>
<button class="save" onclick="savePen()">💾 저장</button>
</div>
<script>
var C=__C__,P=__P__,N=__N__;
var rot=0,lw=-1,sp=false,si=null;

function draw(){
  var s=document.getElementById('sv');s.innerHTML='';
  var sa=360/N;
  for(var i=0;i<N;i++){
    var a1=(i*sa-90-sa/2)*Math.PI/180,a2=((i+1)*sa-90-sa/2)*Math.PI/180;
    var x1=Math.cos(a1)*95,y1=Math.sin(a1)*95,x2=Math.cos(a2)*95,y2=Math.sin(a2)*95;
    var la=sa>180?1:0;
    var c=C[i];
    var p=document.createElementNS('http://www.w3.org/2000/svg','path');
    p.setAttribute('d','M 0 0 L '+x1+' '+y1+' A 95 95 0 '+la+' 1 '+x2+' '+y2+' Z');
    p.setAttribute('fill','rgb('+c[0]+','+c[1]+','+c[2]+')');
    p.setAttribute('stroke','#333');p.setAttribute('stroke-width','1');
    p.setAttribute('id','sl'+i);s.appendChild(p);
    var ma=(i*sa-90)*Math.PI/180,tr=N<=5?60:70;
    var t=document.createElementNS('http://www.w3.org/2000/svg','text');
    t.setAttribute('x',Math.cos(ma)*tr);t.setAttribute('y',Math.sin(ma)*tr);
    t.setAttribute('text-anchor','middle');t.setAttribute('dominant-baseline','middle');
    t.setAttribute('fill','#fff');t.setAttribute('font-size',N<=5?'28':'20');
    t.setAttribute('font-weight','bold');t.textContent=i+1;s.appendChild(t);
  }
}

function drawPen(){
  var f=document.getElementById('pf');f.innerHTML='';
  for(var i=0;i<N;i++){
    var c=C[i];
    var d=document.createElement('div');d.className='pen';
    d.innerHTML='<div class="dot" style="background:rgb('+c[0]+','+c[1]+','+c[2]+')"></div><input name="p'+i+'" value="'+(P[i]||'')+'" maxlength="50">';
    f.appendChild(d);
  }
}

function savePen(){
  var f=document.getElementById('pf');
  var d=new FormData(f);
  fetch('/save',{method:'POST',body:d}).then(function(){alert('저장 완료!');});
}

function go(){
  var b=document.getElementById('sb');
  b.disabled=true;
  fetch('/start');
}

function chg(d){
  var nn=N+d;
  if(nn<2||nn>10)return;
  fetch('/n?v='+nn).then(function(){location.reload();});
}

function hi(i,on){
  var s=document.getElementById('sl'+i);
  if(!s)return;
  s.setAttribute('stroke',on?'#fff':'#333');
  s.setAttribute('stroke-width',on?'4':'1');
}

function clrHi(){for(var i=0;i<N;i++)hi(i,false);}

function spin(){
  var w=document.getElementById('wh');
  w.style.transition='transform 0.1s linear';
  si=setInterval(function(){rot+=72;w.style.transform='rotate('+rot+'deg)';},80);
}

function land(t){
  var w=document.getElementById('wh');
  if(si){clearInterval(si);si=null;}
  var sa=360/N,ta=-(t*sa),cm=rot%360,df=ta-cm;
  if(df>0)df-=360;
  var f=rot+3*360+df;
  w.style.transition='transform 3s cubic-bezier(0.17,0.67,0.21,1)';
  w.style.transform='rotate('+f+'deg)';
  rot=f;
}

function upd(){
  fetch('/s').then(function(r){return r.json();}).then(function(d){
    var st=document.getElementById('st'),cc=document.getElementById('cc'),
        mg=document.getElementById('mg'),ga=document.getElementById('ga'),
        ci=document.getElementById('ci'),sb=document.getElementById('sb');
    ci.innerHTML='<span class="dot-live"></span> 총 '+d.cnt+'회';
    if(d.g===0){
      st.textContent='⏸️ 대기 중';
      cc.className='ctr';cc.innerHTML='🎰<br>START!';
      mg.className='msg w';mg.innerHTML='🎯 START를 누르고<br>5초간 입김을 부세요!';
      ga.classList.remove('on');clrHi();
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
      if(!sp){sp=true;lw=-1;spin();}
      clrHi();hi(d.pos,true);
      sb.disabled=true;sb.textContent='🎰 회전 중';
    }else if(d.g===3){
      st.textContent='✅ 결과!';
      cc.className='ctr';cc.innerHTML='🔄<br>다시!';
      mg.className='msg r';mg.innerHTML='🎉 '+(d.win+1)+'번 당첨!<br>📜 '+P[d.win];
      ga.classList.remove('on');
      if(lw!==d.win){
        lw=d.win;
        if(sp){sp=false;land(d.win);}
        setTimeout(function(){clrHi();hi(d.win,true);},3000);
      }
      sb.disabled=false;sb.textContent='🔄 다시!';
    }
  }).catch(function(e){console.error(e);});
}

window.addEventListener('load',function(){
  draw();drawPen();
  document.getElementById('cc').addEventListener('click',go);
  document.getElementById('sb').addEventListener('click',go);
  document.getElementById('bm').addEventListener('click',function(){chg(-1);});
  document.getElementById('bp').addEventListener('click',function(){chg(1);});
  setInterval(upd,300);upd();
});
</script></body></html>"""

def make_page():
    with lk:
        n = S['n']
        pen = list(S['pen'])
    cs = "[" + ",".join(["[%d,%d,%d]"%(c[0],c[1],c[2]) for c in COLORS[:n]]) + "]"
    ps = "[" + ",".join(['"' + p.replace('"','\\"') + '"' for p in pen[:n]]) + "]"
    h = PAGE.replace("__C__", cs).replace("__P__", ps).replace("__N__", str(n))
    return h

# ============ 유틸 ============
def url_decode(s):
    r = bytearray(); i = 0
    while i < len(s):
        if s[i] == '%':
            try: r.append(int(s[i+1:i+3],16)); i += 3
            except: i += 1
        elif s[i] == '+': r.append(0x20); i += 1
        else: r.append(ord(s[i])); i += 1
    try: return r.decode('utf-8')
    except: return r.decode('utf-8', 'ignore')

def parse_post(b):
    d = {}
    for p in b.split('&'):
        if '=' in p:
            k, v = p.split('=', 1)
            d[k] = url_decode(v)
    return d

def parse_q(p):
    d = {}
    if '?' in p:
        for x in p.split('?',1)[1].split('&'):
            if '=' in x:
                k, v = x.split('=', 1)
                d[k] = v
    return d

# ============ 웹 서버 ============
def server():
    a = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(a); s.listen(3)
    print("서버 시작!")
    while True:
        try:
            cl, _ = s.accept()
            cl.settimeout(3.0)
            req = cl.recv(2048).decode('utf-8')
            fl = req.split('\r\n')[0]
            parts = fl.split(' ')
            m = parts[0] if len(parts)>0 else ''
            p = parts[1] if len(parts)>1 else '/'
            
            if p.startswith('/s'):
                with lk:
                    j = '{"g":%d,"pos":%d,"win":%d,"diff":%d,"mx":%d,"rem":%d,"cnt":%d}' % (
                        S['g'], S['pos'], S['win'], S['diff'], S['mx'], S['rem'], S['cnt'])
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n')
                cl.send(j)
            elif p.startswith('/start'):
                print(">>> START")
                with lk:
                    if S['g'] in (0, 3): S['trig'] = True
                cl.send('HTTP/1.0 200 OK\r\n\r\nOK')
            elif p.startswith('/n'):
                q = parse_q(p)
                if 'v' in q:
                    try:
                        v = int(q['v'])
                        if 2 <= v <= 10:
                            with lk:
                                S['n'] = v
                                S['win'] = -1
                                S['g'] = 0
                            print(">>> 개수:", v)
                    except: pass
                cl.send('HTTP/1.0 200 OK\r\n\r\nOK')
            elif 'POST' in m and '/save' in p:
                if '\r\n\r\n' in req:
                    d = parse_post(req.split('\r\n\r\n',1)[1])
                    with lk:
                        for i in range(S['n']):
                            k = 'p' + str(i)
                            if k in d and d[k].strip():
                                S['pen'][i] = d[k].strip()
                    print("벌칙 저장!")
                cl.send('HTTP/1.0 200 OK\r\n\r\nOK')
            else:
                h = make_page()
                cl.send('HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n')
                cs = 1024
                for i in range(0, len(h), cs):
                    cl.send(h[i:i+cs])
            cl.close()
        except:
            try: cl.close()
            except: pass

# ============ 게임 ============
def measure(base):
    print("측정 시작 (5초)")
    with lk:
        S['g'] = 1; S['mx'] = 0; S['rem'] = 5
    mx = 0
    t0 = time.ticks_ms()
    while True:
        el = time.ticks_diff(time.ticks_ms(), t0)
        rm = 5 - (el // 1000)
        if el >= 5000: break
        v = mq2.read_u16()
        df = abs(v - base)
        if df > mx: mx = df
        show_blow(min(df / 20000, 1.0))
        with lk:
            S['diff'] = df; S['mx'] = mx; S['rem'] = max(0, rm)
        time.sleep(0.05)
    print("최대 변화:", mx)
    return mx

def spin_game(pw):
    with lk: n = S['n']
    print("회전! 파워:", round(pw,2))
    with lk:
        S['g'] = 2; S['cnt'] += 1
    steps = int(15 + pw * 80)
    pos = random.randint(0, n-1)
    for st in range(steps):
        pos = (pos + 1) % n
        show_pointer(pos)
        with lk: S['pos'] = pos
        pr = st / steps
        time.sleep(0.04 + (pr**2.5) * 0.5)
    with lk:
        S['win'] = pos; S['g'] = 3
        wp = S['pen'][pos]
    print("당첨!", pos+1, "번 -", wp)
    celebrate(pos)
    show_pointer(pos)

def calib():
    print("예열 중...")
    sm = []
    for i in range(20):
        sm.append(mq2.read_u16())
        for j in range(cfg.NUM_LEDS):
            led[j] = hsv((i*18+j*36)%360, 1.0, 0.3)
        led.write()
        time.sleep(0.3)
    b = sum(sm) // len(sm)
    print("베이스:", b)
    return b

# ============ 메인 ============
def main():
    print("\n=== 운명의 룰렛 ===\n")
    ip = wifi()
    if not ip: return
    _thread.start_new_thread(server, ())
    time.sleep(1)
    base = calib()
    with lk: S['base'] = base
    show_idle()
    print("\n준비 완료!", ip)
    while True:
        with lk:
            tg = S['trig']; gs = S['g']
        if tg and gs in (0, 3):
            with lk: S['trig'] = False
            mx = measure(base)
            pw = min(mx / 20000, 1.0)
            if pw < 0.1: pw = 0.1
            spin_game(pw)
            time.sleep(5)
            with lk: S['g'] = 0
            show_idle()
        else:
            v = mq2.read_u16()
            with lk: S['diff'] = abs(v - base)
            time.sleep(0.1)

try:
    main()
except KeyboardInterrupt:
    clr()
except Exception as e:
    clr()
    print("오류:", e)
