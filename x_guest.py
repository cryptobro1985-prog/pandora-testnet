"""Best-effort public X GraphQL reader. Never treats errors as successful polls."""
import datetime,email.utils,json,time,urllib.parse,urllib.request,urllib.error

BEARER="AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
BASE="https://x.com/i/api/graphql/"
QUERY_USERS=["AMIBMjtxEEATh4z8V9GtRg","1VOOyvKkiI3FMmkeDNxM9A","2qvSHpkWTMS9i0zJAwDNiA"]
QUERY_TWEETS_IDS=["7_KBXBpG0zBPRN6UCIV0-w","q6xj5bs0hapm9309hexA_g","hr4gzZONlq23okjU8fIe_A"]
_token=None
_expires=0
_user_ids={}

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
 features={"rweb_video_screen_enabled":False,"rweb_cashtags_enabled":True,"profile_label_improvements_pcf_label_in_post_enabled":True,"responsive_web_profile_redirect_enabled":True,"rweb_tipjar_consumption_enabled":False,"verified_phone_label_enabled":False,"creator_subscriptions_tweet_preview_api_enabled":True,"responsive_web_graphql_timeline_navigation_enabled":True,"premium_content_api_read_enabled":False,"communities_web_enable_tweet_community_results_fetch":True,"c9s_tweet_anatomy_moderator_badge_enabled":True,"responsive_web_grok_analyze_button_fetch_trends_enabled":False,"responsive_web_grok_analyze_post_followups_enabled":True,"rweb_cashtags_composer_attachment_enabled":True,"responsive_web_jetfuel_frame":True,"rweb_sports_post_context_enabled":True,"responsive_web_grok_share_attachment_enabled":True,"responsive_web_grok_annotations_enabled":True,"articles_preview_enabled":True,"responsive_web_edit_tweet_api_enabled":True,"rweb_conversational_replies_downvote_enabled":False,"graphql_is_translatable_rweb_tweet_is_translatable_enabled":True,"view_counts_everywhere_api_enabled":True,"longform_notetweets_consumption_enabled":True,"responsive_web_twitter_article_tweet_consumption_enabled":True,"content_disclosure_indicator_enabled":True,"content_disclosure_ai_generated_indicator_enabled":True,"responsive_web_grok_show_grok_translated_post":True,"responsive_web_grok_analysis_button_from_backend":True,"post_ctas_fetch_enabled":False,"freedom_of_speech_not_reach_fetch_enabled":True,"standardized_nudges_misinfo":True,"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":True,"longform_notetweets_rich_text_read_enabled":True,"longform_notetweets_inline_media_enabled":False,"responsive_web_nested_quote_preview_enabled":True,"responsive_web_grok_image_annotation_enabled":True,"responsive_web_grok_imagine_annotation_enabled":True,"responsive_web_grok_community_note_auto_translation_is_enabled":True,"responsive_web_enhance_cards_enabled":False}
 ident=_user_ids.get(handle.lower())
 if not ident:
  user=None;last=None
  for qid in QUERY_USERS:
   try:
    candidate=graphql(qid,"UserByScreenName",{"variables":{"screen_name":handle,"withGrokTranslatedBio":True},"features":features,"fieldToggles":{"withPayments":False,"withAuxiliaryUserLabels":True}})
    result=candidate.get("data",{}).get("user",{}).get("result") or {}
    if result.get("rest_id"):
     user=candidate;break
   except Exception as exc:last=exc
  if user is None:
   if last:raise last
   raise ValueError("guest_user_not_available")
  result=user.get("data",{}).get("user",{}).get("result") or {}
  ident=result.get("rest_id")
  _user_ids[handle.lower()]=ident
 variables={"userId":ident,"count":20,"includePromotedContent":True,"withQuickPromoteEligibilityTweetFields":True,"withVoice":True}
 data=None;last=None
 for qid in QUERY_TWEETS_IDS:
  try:
   candidate=graphql(qid,"UserTweets",{"variables":variables,"features":features,"fieldToggles":{"withArticlePlainText":False}})
   if candidate.get("data"):
    data=candidate;break
  except Exception as exc:last=exc
 if data is None:
  if last:raise last
  raise ValueError("guest_timeline_unavailable")
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
