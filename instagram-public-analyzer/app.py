from flask import Flask, request, jsonify, Response
import os, re, json, subprocess, tempfile

app = Flask(__name__)
SCRAPER_DIR = os.getenv("SCRAPER_DIR","/opt/render/project/src/instascraper-src")

PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Instagram Public Analyzer</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0b0b10;color:#f7f7fb;font-family:Inter,system-ui,Arial}
.wrap{max-width:900px;margin:0 auto;padding:24px 16px 60px}.hero{background:linear-gradient(145deg,#171722,#101018);border:1px solid #2b2b38;border-radius:24px;padding:24px}
h1{margin:0 0 8px;font-size:30px}p{color:#a6a6b3}.form{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px}
input{flex:1;min-width:220px;padding:16px;border-radius:14px;border:1px solid #30303e;background:#0a0a11;color:#fff;font-size:17px}
button{padding:16px 22px;border:0;border-radius:14px;font-weight:800;cursor:pointer}
button:disabled{opacity:.55}.status{margin-top:16px;padding:14px 16px;border-radius:14px;border:1px solid #2c2c38;background:#111119;display:none}
.ok{border-color:#245c43;background:#102019}.err{border-color:#6c2b39;background:#251116}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:18px}.card{background:#111119;border:1px solid #2a2a36;border-radius:18px;padding:18px}.full{grid-column:1/-1}.label{font-size:13px;color:#9b9baa;margin-bottom:7px}.val{font-size:22px;font-weight:800;word-break:break-word}
.post{margin-top:12px;padding:14px;border:1px solid #292936;border-radius:14px;background:#0d0d14}.meta{font-size:13px;color:#9b9baa}.cap{white-space:pre-wrap;margin-top:8px;line-height:1.4}
a{color:#c6b6ff}.small{font-size:13px;color:#8e8e9c}
@media(max-width:640px){.grid{grid-template-columns:1fr}.form{display:block}button,input{width:100%;margin-top:10px}}
</style>
</head>
<body><div class="wrap">
<div class="hero"><h1>Instagram Public Analyzer</h1><p>Без входа в Instagram. Только данные, которые публичная страница реально отдаёт незалогиненному посетителю.</p>
<form id="f" class="form"><input id="u" placeholder="@username или ссылка Instagram" required><button id="b">Проанализировать</button></form>
<div id="s" class="status"></div><div class="small" style="margin-top:10px">Источник: 2scraper/instagram-scraper · до 12 встроенных публикаций.</div></div>
<div id="r" class="grid"></div>
</div>
<script>
const f=document.getElementById('f'),u=document.getElementById('u'),b=document.getElementById('b'),s=document.getElementById('s'),r=document.getElementById('r');
const esc=x=>String(x??'—').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function card(l,v,cls=''){return '<div class="card '+cls+'"><div class="label">'+esc(l)+'</div><div class="val">'+esc(v)+'</div></div>'}
f.onsubmit=async e=>{e.preventDefault();r.innerHTML='';s.style.display='block';s.className='status';s.textContent='Собираю публичные данные…';b.disabled=true;
try{
 const res=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u.value})});
 const d=await res.json(); if(!res.ok||d.status!=='ok') throw new Error(d.message||'Ошибка');
 s.className='status ok';s.textContent='Готово';
 const p=d.profile||{}, posts=d.posts||[];
 r.innerHTML=card('Аккаунт','@'+(p.username||d.username))+card('Имя',p.full_name||p.title||'—')+
 card('Подписчики',p.follower_count??'—')+card('Подписки',p.following_count??'—')+
 card('Верифицирован',p.is_verified===true?'Да':p.is_verified===false?'Нет':'—')+card('Приватный',p.is_private===true?'Да':p.is_private===false?'Нет':'—')+
 '<div class="card full"><div class="label">Bio</div><div>'+esc(p.biography||'—')+'</div></div>'+
 '<div class="card full"><div class="label">Публикации ('+posts.length+')</div>'+
 posts.map(x=>'<div class="post"><div class="meta">'+esc(x.posted_at||'')+' · ❤️ '+esc(x.like_count??'—')+' · 💬 '+esc(x.comment_count??'—')+'</div><div class="cap">'+esc(x.caption||x.title||'')+'</div><div class="meta" style="margin-top:8px">'+esc(x.product_type||x.media_type||'')+(x.product_url?' · <a target="_blank" href="'+esc(x.product_url)+'">открыть</a>':'')+'</div></div>').join('')+
 '</div>';
}catch(e){s.className='status err';s.textContent=e.message||String(e)}
finally{b.disabled=false}
}
</script></body></html>"""

def norm(raw):
    raw=(raw or "").strip()
    m=re.search(r"instagram\.com/([^/?#]+)",raw,re.I)
    if m: raw=m.group(1)
    return raw.lstrip("@").strip("/")

@app.get("/")
def home(): return Response(PAGE,mimetype="text/html")

@app.get("/health")
def health(): return jsonify({"status":"ok","scraper_dir":SCRAPER_DIR})

def run_scrape(username):
    if not username: return {"status":"error","message":"Введи username."},400
    with tempfile.TemporaryDirectory() as td:
        out=os.path.join(td,"result.json")
        cmd=["python3",os.path.join(SCRAPER_DIR,"playwright_scraper.py"),"--url",username,"--posts","12","--format","json","--out",out,"--delay-between-pages","1.2","--retries","1","--solve-captcha","off"]
        try:
            cp=subprocess.run(cmd,cwd=SCRAPER_DIR,capture_output=True,text=True,timeout=110)
        except subprocess.TimeoutExpired:
            return {"status":"error","message":"Instagram не ответил вовремя. Повтори попытку."},504
        rows=[]
        if os.path.exists(out):
            try:
                rows=json.load(open(out,"r",encoding="utf-8"))
            except Exception:
                rows=[]
        if not rows:
            detail=(cp.stderr or cp.stdout or "").strip()
            low=detail.lower()
            if "login page" in low or "blocked" in low or "rate_limited" in low or "login required" in low:
                msg="Instagram отдал серверу страницу входа вместо публичных данных. Это ограничение Instagram для дата-центров, а не ошибка интерфейса."
            else:
                msg="2scraper не получил публичные данные с Instagram."
            return {"status":"error","message":msg,"detail":detail[-1200:],"exit_code":cp.returncode},502
        profile=next((x for x in rows if x.get("category")=="profile"),{})
        posts=[x for x in rows if x.get("category")=="post"]
        return {"status":"ok","username":username,"profile":profile,"posts":posts,"count":len(rows),"exit_code":cp.returncode},200

@app.post("/api/analyze")
def analyze():
    username=norm((request.get_json(silent=True) or {}).get("username",""))
    body,code=run_scrape(username)
    return jsonify(body),code

@app.get("/api/smoke")
def smoke():
    username=norm(request.args.get("username","natgeo"))
    body,code=run_scrape(username)
    return jsonify(body),code

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
