"""Read-only X List timeline poller using a normal browser session.
No developer API key. Activates only when X_AUTH_TOKEN, X_CT0 and X_LIST_ID are set.
"""
import datetime as dt
import email.utils
import json
import time
import urllib.parse
from curl_cffi import requests as curl_requests

BEARER="AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs=1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
OP="ListLatestTweetsTimeline"
FALLBACK_QUERY_ID="RgfF9JYDXXI1F-ZrDqjUfQ"
OPENAPI="https://raw.githubusercontent.com/fa0311/twitter-openapi/refs/heads/main/src/config/placeholder.json"
_cached=None
_cached_at=0.0

DEFAULT_FEATURES={
 "rweb_video_screen_enabled":False,
 "rweb_cashtags_enabled":True,
 "profile_label_improvements_pcf_label_in_post_enabled":True,
 "responsive_web_profile_redirect_enabled":True,
 "rweb_tipjar_consumption_enabled":False,
 "verified_phone_label_enabled":False,
 "creator_subscriptions_tweet_preview_api_enabled":True,
 "responsive_web_graphql_timeline_navigation_enabled":True,
 "premium_content_api_read_enabled":False,
 "communities_web_enable_tweet_community_results_fetch":True,
 "c9s_tweet_anatomy_moderator_badge_enabled":True,
 "responsive_web_grok_analyze_button_fetch_trends_enabled":False,
 "responsive_web_grok_analyze_post_followups_enabled":True,
 "rweb_cashtags_composer_attachment_enabled":True,
 "responsive_web_jetfuel_frame":True,
 "rweb_sports_post_context_enabled":True,
 "responsive_web_grok_share_attachment_enabled":True,
 "rweb_grok_annotations_enabled":True,
 "articles_preview_enabled":True,
 "responsive_web_edit_tweet_api_enabled":True,
 "rweb_conversational_replies_downvote_enabled":False,
 "graphql_is_translatable_rweb_tweet_is_translatable_enabled":True,
 "view_counts_everywhere_api_enabled":True,
 "longform_notetweets_consumption_enabled":True,
 "responsive_web_twitter_article_tweet_consumption_enabled":True,
 "content_disclosure_indicator_enabled":True,
 "content_disclosure_ai_generated_indicator_enabled":True,
 "responsive_web_grok_show_grok_translated_post":True,
 "responsive_web_grok_analysis_button_from_backend":True,
 "post_ctas_fetch_enabled":False,
 "freedom_of_speech_not_reach_fetch_enabled":True,
 "standardized_nudges_misinfo":True,
 "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled":True,
 "longform_notetweets_rich_text_read_enabled":True,
 "longform_notetweets_inline_media_enabled":False,
 "responsive_web_nested_quote_preview_enabled":True,
 "responsive_web_grok_image_annotation_enabled":True,
 "responsive_web_grok_imagine_annotation_enabled":True,
 "responsive_web_grok_community_note_auto_translation_is_enabled":True,
 "responsive_web_enhance_cards_enabled":False
}

def definition():
 global _cached,_cached_at
 if _cached and time.time()-_cached_at<21600:return _cached
 try:
  s=curl_requests.Session()
  r=s.get(OPENAPI,impersonate="chrome146",timeout=8)
  if r.status_code==200:
   item=(r.json() or {}).get(OP) or {}
   q=item.get("queryId") or FALLBACK_QUERY_ID
   features=item.get("features") or DEFAULT_FEATURES
   _cached=(q,features);_cached_at=time.time();return _cached
 except Exception:
  pass
 _cached=(FALLBACK_QUERY_ID,DEFAULT_FEATURES);_cached_at=time.time();return _cached

def _headers(auth_token,ct0):
 return {
  "Authorization":"Bearer "+BEARER,
  "Cookie":"auth_token="+auth_token+"; ct0="+ct0,
  "X-Csrf-Token":ct0,
  "X-Twitter-Active-User":"yes",
  "X-Twitter-Auth-Type":"OAuth2Session",
  "X-Twitter-Client-Language":"en",
  "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
  "Origin":"https://x.com","Referer":"https://x.com/","Accept":"*/*"
 }

def _created(value):
 if not value:return None
 try:return email.utils.parsedate_to_datetime(value).astimezone(dt.timezone.utc).isoformat()
 except Exception:return value

def fetch_list(list_id,auth_token,ct0,count=100,timeout=8):
 qid,features=definition()
 variables={"listId":str(list_id),"count":min(max(int(count),20),100)}
 params={"variables":json.dumps(variables,separators=(",",":")),"features":json.dumps(features,separators=(",",":"))}
 url="https://x.com/i/api/graphql/"+qid+"/"+OP+"?"+urllib.parse.urlencode(params)
 s=curl_requests.Session()
 r=s.get(url,headers=_headers(auth_token,ct0),impersonate="chrome146",timeout=timeout)
 if r.status_code in (404,422):
  global _cached_at
  _cached_at=0
  qid,features=definition()
  params={"variables":json.dumps(variables,separators=(",",":")),"features":json.dumps(features,separators=(",",":"))}
  url="https://x.com/i/api/graphql/"+qid+"/"+OP+"?"+urllib.parse.urlencode(params)
  r=s.get(url,headers=_headers(auth_token,ct0),impersonate="chrome146",timeout=timeout)
 if r.status_code!=200:raise RuntimeError("x_list_http_"+str(r.status_code))
 payload=r.json()
 if isinstance(payload,dict) and payload.get("errors"):
  raise RuntimeError("x_list_graphql_"+str(payload.get("errors"))[:120])
 found={}
 def walk(node):
  if isinstance(node,list):
   for v in node:walk(v)
  elif isinstance(node,dict):
   legacy=node.get("legacy")
   if isinstance(legacy,dict) and (node.get("__typename")=="Tweet" or node.get("rest_id")):
    ident=str(legacy.get("id_str") or node.get("rest_id") or "")
    text=(legacy.get("full_text") or "").strip()
    stamp=legacy.get("created_at")
    author=(node.get("core") or {}).get("user_results",{}).get("result",{})
    handle=((author.get("legacy") or {}).get("screen_name") or (author.get("core") or {}).get("screen_name") or "")
    if ident and text and stamp and handle:
     found[ident]={"id":ident,"text":text,"created_at":_created(stamp),"handle":handle,"url":"https://x.com/"+handle+"/status/"+ident}
   for v in node.values():walk(v)
 walk(payload)
 if not found:raise RuntimeError("x_list_empty_or_schema_changed")
 return list(found.values())
