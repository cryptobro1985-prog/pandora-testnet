import os,json,urllib.request,urllib.parse
WATCH=["elonmusk","realDonaldTrump","federalreserve","SECGov","USTreasury","WhiteHouse","coinbase","binance","saylor","cz_binance","VitalikButerin"]
def recent():
 token=os.getenv("X_BEARER_TOKEN","").strip()
 if not token:return []
 q="("+" OR ".join("from:"+x for x in WATCH)+") -is:retweet"
 url="https://api.x.com/2/tweets/search/recent?"+urllib.parse.urlencode({"query":q,"max_results":100,"tweet.fields":"created_at,author_id"})
 req=urllib.request.Request(url,headers={"Authorization":"Bearer "+token,"User-Agent":"PANDORA-paper/1"})
 with urllib.request.urlopen(req,timeout=15) as r:return json.load(r).get("data",[])
