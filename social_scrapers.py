"""Isolated, bounded open-source social readers. Never prints credentials."""
import asyncio
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import time

class SourceUnavailable(RuntimeError):
    pass

def plain(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub('<[^>]+>', ' ', value or ''))).strip()

async def read_x(handles):
    cookies = os.getenv('X_SESSION_COOKIES', '').strip()
    if not cookies:
        raise SourceUnavailable('needs_x_session')
    from twscrape import API
    api = API('/tmp/pandora-x-sessions.sqlite', raise_when_no_account=True,
              wait_timeout=2, wait_interval=1)
    await api.pool.add_account_cookies('pandora_reader', cookies)
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=3)).strftime('%Y-%m-%d_%H:%M:%S_UTC')
    query = '(' + ' OR '.join('from:' + h for h in handles) + ') -filter:retweets since:' + since
    result = []
    async for tweet in api.search(query, limit=100, kv={'product': 'Latest'}):
        result.append({'id': str(tweet.id), 'text': tweet.rawContent,
                       'created_at': tweet.date.isoformat(), 'url': tweet.url})
    return result

def read_truth(handle):
    # Use truthbrush's session with an explicit timeout and HTTP checks. Its
    # pagination can silently swallow failures and walk old history, so only
    # fetch the latest bounded page through the client's transport.
    from truthbrush import Api
    from truthbrush.api import API_BASE_URL
    token = os.getenv('TRUTHSOCIAL_TOKEN', '').strip() or None
    api = Api(username=None, password=None, token=token)
    session = api._make_session()
    try:
        headers = {'Accept': 'application/json', 'User-Agent': 'Pandora-news-reader/1'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        def get(path, params):
            response = session.get(API_BASE_URL + path, params=params, headers=headers, timeout=12)
            if response.status_code != 200:
                raise SourceUnavailable('truth_http_' + str(response.status_code))
            return response.json()
        account = get('/v1/accounts/lookup', {'acct': handle})
        if not isinstance(account, dict) or not account.get('id'):
            raise SourceUnavailable('truth_invalid_account')
        posts = get('/v1/accounts/' + str(account['id']) + '/statuses',
                    {'limit': 20, 'exclude_replies': 'true'})
        if not isinstance(posts, list):
            raise SourceUnavailable('truth_invalid_posts')
        return [{'id': str(p['id']), 'text': plain(p.get('content')),
                 'created_at': p.get('created_at'), 'url': p.get('url')}
                for p in posts if isinstance(p, dict) and p.get('id')]
    finally:
        session.close()

def poll(kind, handles):
    child_env = dict(os.environ, TWS_TELEMETRY='0')
    try:
        result = subprocess.run([sys.executable, os.path.abspath(__file__), kind, *handles],
                                env=child_env, capture_output=True, text=True, timeout=35)
    except subprocess.TimeoutExpired:
        raise SourceUnavailable('source_timeout') from None
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise SourceUnavailable('reader_failed') from None
    if not payload.get('ok'):
        raise SourceUnavailable(payload.get('error', 'reader_failed'))
    return payload['posts']

if __name__ == '__main__':
    try:
        started = time.monotonic()
        posts = asyncio.run(read_x(sys.argv[2:])) if sys.argv[1] == 'x' else read_truth(sys.argv[2])
        print(json.dumps({'ok': True, 'posts': posts, 'duration_seconds': time.monotonic()-started}))
    except Exception as exc:
        # Exception strings / library logs may contain cookies or tokens.
        error = str(exc) if isinstance(exc, SourceUnavailable) else type(exc).__name__
        print(json.dumps({'ok': False, 'error': error}))
        sys.exit(1)
