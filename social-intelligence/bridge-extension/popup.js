const BACKEND="https://social-intelligence-live-v2.onrender.com";
const $=id=>document.getElementById(id);
function clean(v){return String(v||"").trim().replace(/^@/,"").replace(/^https?:\/\/(www\.)?instagram\.com\//i,"").split(/[/?#]/)[0]}
async function collectInPage(username){
  const IG_APP_ID="936619743392459", IG_ASBD_ID="359341";
  const cookie=(name)=>{
    const row=document.cookie.split("; ").find(x=>x.startsWith(name+"="));
    return row?decodeURIComponent(row.slice(name.length+1)):"";
  };
  const csrf=cookie("csrftoken");
  const baseHeaders={"x-ig-app-id":IG_APP_ID,"x-asbd-id":IG_ASBD_ID,"x-requested-with":"XMLHttpRequest","x-ig-www-claim":"0"};
  if(csrf) baseHeaders["x-csrftoken"]=csrf;
  async function jfetch(url){
    const r=await fetch(url,{headers:baseHeaders,credentials:"include"});
    let body=null;try{body=await r.json()}catch(e){}
    if(!r.ok) throw new Error("Instagram HTTP "+r.status);
    return body;
  }
  const info=await jfetch("/api/v1/users/web_profile_info/?username="+encodeURIComponent(username));
  const u=info&&info.data&&info.data.user;
  if(!u) throw new Error("Profile not found");
  if(u.is_private) throw new Error("Private profiles are not scanned");
  const profile={
    username:u.username||username,user_id:String(u.id||u.pk||""),name:u.full_name||"",biography:u.biography||"",
    profile_picture_url:u.profile_pic_url_hd||u.profile_pic_url||null,is_verified:!!u.is_verified,is_private:!!u.is_private,
    followers_count:u.edge_followed_by&&u.edge_followed_by.count!=null?u.edge_followed_by.count:null,
    follows_count:u.edge_follow&&u.edge_follow.count!=null?u.edge_follow.count:null,
    media_count:u.edge_owner_to_timeline_media&&u.edge_owner_to_timeline_media.count!=null?u.edge_owner_to_timeline_media.count:null
  };
  const posts=[];
  const edges=(u.edge_owner_to_timeline_media&&u.edge_owner_to_timeline_media.edges)||[];
  for(const e of edges.slice(0,24)){
    const n=e&&e.node;if(!n)continue;
    const cap=n.edge_media_to_caption&&n.edge_media_to_caption.edges&&n.edge_media_to_caption.edges[0];
    posts.push({
      id:n.id||null,shortcode:n.shortcode||null,permalink:n.shortcode?"https://www.instagram.com/p/"+n.shortcode+"/":null,
      timestamp:n.taken_at_timestamp?new Date(n.taken_at_timestamp*1000).toISOString():null,
      caption:cap&&cap.node&&cap.node.text||"",
      like_count:n.edge_liked_by&&n.edge_liked_by.count!=null?n.edge_liked_by.count:(n.edge_media_preview_like&&n.edge_media_preview_like.count!=null?n.edge_media_preview_like.count:null),
      comments_count:n.edge_media_to_comment&&n.edge_media_to_comment.count!=null?n.edge_media_to_comment.count:null,
      comments_detail:[],likers:[]
    });
  }
  async function people(kind){
    const out=[];let max=null;let pages=0;
    while(pages<400 && out.length<20000){
      const q=new URLSearchParams({count:"50"});if(max)q.set("max_id",max);
      const body=await jfetch("/api/v1/friendships/"+profile.user_id+"/"+kind+"/?"+q.toString());
      for(const x of body.users||[]){
        if(x&&x.username)out.push({pk:String(x.pk||x.id||x.username),username:x.username,full_name:x.full_name||"",is_verified:!!x.is_verified,is_private:!!x.is_private});
      }
      max=body.next_max_id||null;pages++;
      if(!max||body.big_list===false)break;
      await new Promise(r=>setTimeout(r,350));
    }
    return out;
  }
  const following=await people("following");
  const followers=await people("followers");
  return {username:profile.username,profile,followers,following,posts,source:"browser_bridge"};
}
async function run(){
  const username=clean($("u").value);if(!username){$("status").textContent="Введите username";return}
  $("status").textContent="Сканирование…";
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if(!tab||!/^https:\/\/(www\.)?instagram\.com\//i.test(tab.url||"")){
    $("status").textContent="Сначала откройте instagram.com в этой вкладке и войдите в аккаунт.";return;
  }
  try{
    const res=await chrome.scripting.executeScript({target:{tabId:tab.id},world:"MAIN",func:collectInPage,args:[username]});
    const payload=res&&res[0]&&res[0].result;if(!payload)throw new Error("No data returned");
    $("status").textContent="Отправка в Intelligence…";
    const r=await fetch(BACKEND+"/api/bridge/ingest",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const j=await r.json();if(!r.ok)throw new Error(j.detail||("Backend HTTP "+r.status));
    $("status").textContent="Готово: followers "+j.followers+", following "+j.following+", posts "+j.posts+". Теперь нажмите FULL SCAN в мини-аппе.";
  }catch(e){$("status").textContent="Ошибка: "+(e&&e.message||String(e))}
}
$("go").onclick=run;