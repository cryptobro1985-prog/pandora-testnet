"""Best-effort public X GraphQL reader. Never treats errors as successful polls."""
import datetime,email.utils,json,time,urllib.parse,urllib.request,urllib.error

BEARER="AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
BASE="https://x.com/i/api/graphql/"
QUERY_USER="2qvSHpkWTMS9i0zJAwDNiA"
QUERY_TWEETS="hr4gzZONlq23okjU8fIe_A"
_token=None
_expires=0

def request(url,headers,post=False):
 req=urllib.request.Request(url,headers=headers,method="POST" if post else "GET")
 with urllib.request.urlopen(req,timeout=8) as r:
  data=r.read(2_000_000)
 return json.loads(data)

def headers():
 global _token,_expires
 if not _token or time.time()>_expires:
  result=request("https://api.x.com/1.1/guest/activate.json",{"Authorization":"Bearer "+BEARER,"User-Agent":"Mozilla/5.0","Content-Type":"application/x-www-form-urlencoded"},True)
  _token=result["guest_token"];_expires=time.time()+780
 return {"Authorization":"Bearer "+BEARER,"X-Guest-Token":_token,"User-Agent":"Mozilla/5.0","x-twitter-active-user":"yes","Accept":"application/json"}

def graphql(qid,op,params):
 url=BASE+qid+"/"+op+"?"+urllib.parse.urlencode({k:json.dumps(v,separators=(",",":")) for k,v in params.items()})
 try:return request(url,headers())
 except urllib.error.HTTPError as e:
  if e.code in (401,403): 
   global _expires
   _expires=0
  raise

def read(handle):
 features={"responsive_web_graphql_exclude_directive_enabled":True,"verified_phone_label_enabled":False,"responsive_web_graphql_timeline_navigation_enabled":True,"rweb_tipjar_consumption_enabled":True,"creator_subscriptions_tweet_preview_api_enabled":True,"responsive_web_graphql_skip_user_profile_image_extensions_enabled":False}
 user=graphql(QUERY_USER,"UserByScreenName",{"variables":{"screen_name":handle,"withSafetyModeUserFields":True},"features":features})
 result=user.get("data",{}).get("user",{}).get("result") or {}
 ident=result.get("rest_id")
 if not ident:raise ValueError("guest_user_not_available")
 variables={"userId":ident,"count":20,"includePromotedContent":False,"withQuickPromoteEligibilityTweetFields":False,"withVoice":True,"withV2Timeline":True}
 data=graphql(QUERY_TWEETS,"UserTweets",{"variables":variables,"features":features,"fieldToggles":{"withArticlePlainText":False}})
 found={}
 def walk(node):
  if isinstance(node,list):
   for v in node:walk(v)
  elif isinstance(node,dict):
   if node.get("__typename")=="Tweet" and isinstance(node.get("legacy"),dict):
    legacy=node["legacy"];id_=legacy.get("id_str") or node.get("rest_id")
    text=legacy.get("full_text")
    stamp=legacy.get("created_at")
    if id_ and text and stamp and not text.startswith("RT @"):
     author=(node.get("core") or {}).get("user_results",{}).get("result",{})
     username=(author.get("legacy") or {}).get("screen_name") or (author.get("core") or {}).get("screen_name")
     if username and username.lower()==handle.lower():
      found[id_]={"id":id_,"text":text,"created_at":email.utils.parsedate_to_datetime(stamp).isoformat(),"url":"https://x.com/"+handle+"/status/"+id_}
   for k,v in node.items():
    if k not in ("quoted_status_result","retweeted_status_result"):walk(v)
 walk(data)
 if not found:raise ValueError("guest_timeline_empty_or_schema_changed")
 return list(found.values())
