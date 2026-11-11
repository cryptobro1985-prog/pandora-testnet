from flask import Flask, request, jsonify, Response, redirect, session
import os, re, html, requests

app = Flask(__name__)\napp.secret_key = os.getenv("FLASK_SECRET_KEY","change-me-in-render")\nIG_CLIENT_ID=os.getenv("INSTAGRAM_CLIENT_ID","")\nIG_CLIENT_SECRET=os.getenv("INSTAGRAM_CLIENT_SECRET","")\nIG_REDIRECT_URI=os.getenv("INSTAGRAM_REDIRECT_URI","https://instatrack-simple-ui.onrender.com/auth/instagram/callback")\nIG_SCOPES=os.getenv("INSTAGRAM_SCOPES","instagram_business_basic").strip()
BACKEND = os.getenv("INSTATRACK_BACKEND_URL","https://instatrack-mohammedelahmar-live-v2.onrender.com").rstrip("/")

PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>InstaTrack Simple</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;font-family:Inter,system-ui,Arial;background:#0a0a0f;color:#f6f6f8;min-height:100vh}
.wrap{max-width:820px;margin:0 auto;padding:28px 16px 64px}.hero{padding:28px;border:1px solid #272735;border-radius:24px;background:linear-gradient(145deg,#151522,#0f0f17);box-shadow:0 18px 60px #0007}
h1{margin:0 0 8px;font-size:32px}p{color:#a8a8b8}.form{display:flex;gap:10px;margin-top:24px;flex-wrap:wrap}
input{flex:1;min-width:230px;padding:16px 18px;border-radius:14px;border:1px solid #30303c;background:#0b0b12;color:#fff;font-size:17px;outline:none}
button{padding:16px 22px;border:0;border-radius:14px;background:#fff;color:#111;font-weight:800;font-size:16px;cursor:pointer}
button:disabled{opacity:.55;cursor:wait}.status{margin-top:18px;padding:14px 16px;border-radius:14px;background:#111119;border:1px solid #272735;display:none}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-top:18px}.card{padding:18px;border:1px solid #272735;border-radius:18px;background:#111119}.card h3{margin:0 0 10px;font-size:14px;color:#9e9eae}.big{font-size:25px;font-weight:800}.mono{font-family:ui-monospace,monospace;word-break:break-word}.error{border-color:#6b2633;background:#241117}.ok{border-color:#245b43;background:#102019}.muted{color:#8d8d9c}.full{grid-column:1/-1}.list{margin:0;padding-left:18px}.list li{margin:5px 0}
@media(max-width:640px){.grid{grid-template-columns:1fr}.hero{padding:20px}h1{font-size:28px}.form{display:block}button,input{width:100%;margin-top:10px}}
</style>
</head>
<body><div class="wrap">
<div class="hero">
<h1>InstaTrack</h1><p>Введи Instagram-аккаунт и запусти анализ.</p>
<form id="f" class="form"><input id="u" autocomplete="off" placeholder="@username или ссылка Instagram" required><button id="b">Проанализировать</button></form>
<details style="margin-top:14px"><summary style="cursor:pointer;color:#aaaabd">Если Instagram просит авторизацию — добавить sessionid</summary>
<div style="margin-top:10px"><input id="sid" type="password" autocomplete="off" placeholder="Instagram sessionid (не пароль)" style="width:100%"><p class="muted" style="font-size:13px;margin:8px 2px 0">Используется только для текущего анализа и не сохраняется этой оболочкой.</p></div>
</details>
<div id="s" class="status"></div>
</div>
<div id="r" class="grid"></div>
</div>
<script>
const f=document.getElementById('f'),u=document.getElementById('u'),sid=document.getElementById('sid'),b=document.getElementById('b'),s=document.getElementById('s'),r=document.getElementById('r');
const esc=x=>String(x??'—').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
function card(t,v,cls=''){return '<div class="card '+cls+'"><h3>'+esc(t)+'</h3><div class="big">'+esc(v)+'</div></div>'}
f.onsubmit=async(e)=>{e.preventDefault();r.innerHTML='';s.style.display='block';s.className='status';s.textContent='Анализирую…';b.disabled=true;
try{
 const res=await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u.value,session_id:sid.value})});
 const d=await res.json(); if(!res.ok||d.status!=='ok') throw new Error(d.message||'Ошибка анализа');
 s.className='status ok';s.textContent='Готово';
 const p=d.profile||{}, snap=d.snapshot||{}, rel=d.relationships||[];
 r.innerHTML=card('Аккаунт','@'+(p.username||d.username))+card('Имя',p.full_name||'—')+
 card('Подписчики',p.follower_count??'—')+card('Подписки',p.following_count??'—')+
 card('Приватный',p.is_private===true?'Да':p.is_private===false?'Нет':'—')+card('Верифицирован',p.is_verified===true?'Да':p.is_verified===false?'Нет':'—')+
 '<div class="card full"><h3>Снимок</h3><div class="mono">'+esc(JSON.stringify(snap,null,2))+'</div></div>'+
 '<div class="card full"><h3>Отношения</h3><div class="mono">'+esc(JSON.stringify(rel,null,2))+'</div></div>';
}catch(err){s.className='status error';s.textContent=err.message||String(err);}
finally{b.disabled=false}
}
</script></body></html>"""

def normalize_username(raw: str) -> str:
    raw=(raw or "").strip()
    if not raw: return ""
    m=re.search(r"instagram\.com/([^/?#]+)", raw, re.I)
    if m: raw=m.group(1)
    return raw.lstrip("@").strip("/").strip()

def backend(method, path, **kwargs):
    try:
        r=requests.request(method, BACKEND+path, timeout=70, **kwargs)
        try: data=r.json()
        except Exception: data={"message":r.text[:500]}
        return r, data
    except requests.RequestException as e:
        return None, {"message":f"Backend недоступен: {e}"}

@app.get("/")
def index(): return Response(PAGE, mimetype="text/html")

@app.get("/health")
def health(): return jsonify({"status":"ok","backend":BACKEND})

@app.post("/api/analyze")
def analyze():
    payload=request.get_json(silent=True) or {}
    username=normalize_username(payload.get("username",""))
    session_id=(payload.get("session_id") or "").strip()
    if not username: return jsonify({"status":"error","message":"Введи username или ссылку Instagram."}),400

    # If the user supplied their own authorized Instagram session, pass it to
    # the original InstaTrack backend for this runtime only. Do not persist it.
    if session_id:
        ar,ad=backend("POST","/api/settings/session",json={"session_id":session_id,"persist":False})
        if ar is None:
            return jsonify({"status":"error","message":ad.get("message","Не удалось передать Instagram sessionid.")}),502
        if ar.status_code>=400 or (isinstance(ad,dict) and ad.get("status")=="error"):
            return jsonify({"status":"error","message":(ad.get("message") if isinstance(ad,dict) else "Instagram sessionid не принят.")}),400

    # 1) live profile through original InstaTrack backend
    pr,pd=backend("GET",f"/api/profile/{username}")
    if pr is None: return jsonify({"status":"error","message":pd.get("message")}),502
    if pr.status_code>=400 or pd.get("status")=="error":
        msg=pd.get("message") or "Не удалось получить профиль"
        low=str(msg).lower()
        if "credentials are not configured" in low or "session" in low or "login" in low:
            msg="Instagram требует авторизованную сессию. Раскрой пункт «добавить sessionid», вставь sessionid своего Instagram и нажми «Проанализировать» ещё раз."
        return jsonify({"status":"error","message":msg}),pr.status_code if pr.status_code>=400 else 400
    profile=pd.get("profile") or {}

    # 2) run one snapshot for this account
    sr,sd=backend("POST","/api/snapshot",json={"account":username})
    snapshot = sd if isinstance(sd,dict) else {}

    # 3) relationships/report if available
    rr,rd=backend("GET","/api/relationships",params={"account":username,"limit":50})
    relationships = rd.get("relationships",[]) if isinstance(rd,dict) else []

    result={
      "status":"ok","username":username,"profile":profile,
      "snapshot":snapshot,
      "relationships":relationships,
      "warnings":[]
    }
    if sr is None or (sr and sr.status_code>=400):
        result["warnings"].append(snapshot.get("message","Snapshot не выполнен"))
    if rr is None or (rr and rr.status_code>=400):
        result["warnings"].append("Relationships недоступны")
    return jsonify(result)

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT","10000")))
