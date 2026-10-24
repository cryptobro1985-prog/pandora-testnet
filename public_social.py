"""Read public X pages and Trump's public RSS archive without account sessions."""
import datetime as dt
import html
import json
import re
import urllib.request
import xml.etree.ElementTree as ET

class PublicReadError(RuntimeError):
    pass

def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'Pandora-public-reader/1',
                                           'Accept':'text/html,application/rss+xml'})
    with urllib.request.urlopen(req,timeout=12) as response:
        data=response.read(3_000_001)
    if len(data)>3_000_000:raise PublicReadError('page_too_large')
    return data.decode('utf-8')

def x_posts(page,handle):
    # Decode JSON string literals, never execute scripts from an external page.
    payloads=[]
    for match in re.finditer(r'"(?:\\.|[^"\\])*"',page):
        if 'full_text' not in match.group():continue
        try:
            value=json.loads(match.group())
            if isinstance(value,str):value=json.loads(value)
            if isinstance(value,(dict,list)):payloads.append(value)
        except (ValueError,TypeError):continue
    posts={}
    def visit(node):
        if isinstance(node,dict):
            details=node.get('details',{})
            user=node.get('core',{}).get('user_results',{}).get('result',{})
            author=user.get('core',{}).get('screen_name') or user.get('legacy',{}).get('screen_name')
            if isinstance(details,dict) and details.get('full_text') and str(author).lower()==handle.lower():
                ident=node.get('rest_id');stamp=details.get('created_at_ms')
                if ident and isinstance(stamp,(int,float)):
                    posts[str(ident)]={'id':str(ident),'text':details['full_text'],
                        'created_at':dt.datetime.fromtimestamp(stamp/1000,dt.timezone.utc).isoformat(),
                        'url':'https://x.com/'+handle+'/status/'+str(ident)}
            # Quoted posts and repost payloads must not become separate author signals.
            for key,value in node.items():
                if key not in ('quoted_tweet_results','retweeted_status_result'):visit(value)
        elif isinstance(node,list):
            for value in node:visit(value)
    visit(payloads)
    if not posts:raise PublicReadError('no_public_posts_or_schema_changed')
    return sorted(posts.values(),key=lambda p:p['created_at'])

def archive_posts(page):
    root=ET.fromstring(page)
    posts=[]
    for item in root.findall('.//item'):
        text=html.unescape(re.sub('<[^>]+>',' ',item.findtext('description') or ''))
        text=re.sub(r'\s+',' ',text).strip()
        # Image-only/archive-generated titles are not trading text.
        if not text or text in ('View image','View video'):continue
        link=item.findtext('link')
        if link:
            posts.append({'id':link,'text':text,'created_at':item.findtext('pubDate'),'url':link})
    return posts

def read(kind,handle):
    if kind=='x':return x_posts(fetch('https://x.com/'+handle),handle)
    return archive_posts(fetch('https://www.trumpstruth.org/feed?limit=20'))
