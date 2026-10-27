"""Process-wide, nonblocking REST budget. Never sleep in an exit/price worker."""
from collections import deque
import email.utils
import math
import threading
import time


class RestDeferred(RuntimeError):
    pass


class RestBudget:
    def __init__(self, limit=600, clock=time.monotonic, wall=time.time):
        self.limit = limit
        self.clock, self.wall = clock, wall
        self.lock = threading.RLock()
        self.used = deque()
        self.until = 0.0
        self.failures = 0
        self.last_429 = None
        self.sent = self.deferred = self.rate_limited = 0

    @staticmethod
    def weight(body):
        kind = (body or {}).get('type')
        if kind in ('l2Book', 'allMids', 'clearinghouseState', 'orderStatus', 'spotClearinghouseState', 'exchangeStatus'):
            return 2
        if kind in ('userFills', 'userFillsByTime', 'historicalOrders', 'recentTrades'):
            return 120  # conservative reservation for response-size surcharges
        if kind == 'userRole':
            return 60
        if kind == 'candleSnapshot':
            req = body.get('req', {})
            interval = {'1m':60000, '15m':900000, '1h':3600000}.get(req.get('interval'), 60000)
            count = max(0, (req.get('endTime', 0)-req.get('startTime', 0)) // interval + 1)
            return 20 + math.ceil(count / 60)
        return 20

    def acquire(self, body):
        with self.lock:
            now = self.clock()
            while self.used and now-self.used[0][0] >= 60:
                self.used.popleft()
            weight = self.weight(body)
            # Reserve capacity for LOCAL history/price recovery over bulk research.
            priority = body.get('type') == 'allMids' or (body.get('type') == 'candleSnapshot' and body.get('req',{}).get('interval') in ('1h','15m'))
            ceiling = self.limit if priority else max(1, self.limit-100)
            if now < self.until or sum(w for _,w in self.used)+weight > ceiling:
                self.deferred += 1
                raise RestDeferred('hyperliquid_rest_deferred:shared_budget_or_cooldown')
            self.used.append((now,weight)); self.sent += 1

    def limited(self, retry_after=None):
        with self.lock:
            now = self.clock()
            if now >= self.until:
                self.failures += 1
                self.limit = min(self.limit, max(120, self.limit // 2))
            self.rate_limited += 1; self.last_429 = self.wall()
            delay = min(300, 30 * 2**min(self.failures-1,4))
            if retry_after:
                try:
                    value = float(retry_after)
                except (ValueError, TypeError):
                    try:value = email.utils.parsedate_to_datetime(retry_after).timestamp()-self.wall()
                    except (ValueError, TypeError, OverflowError):value = 0
                if math.isfinite(value):delay = max(delay,value)
            self.until = max(self.until, now+delay)

    def success(self):
        with self.lock:
            # A single successful in-flight response must not cancel an active ban.
            if self.clock() >= self.until and self.last_429 is not None and self.wall()-self.last_429 >= 120:
                self.failures = 0

    def status(self):
        with self.lock:
            now=self.clock()
            return {'budget_per_minute':self.limit,'used_weight_60s':sum(w for t,w in self.used if now-t<60),
                    'cooldown_seconds':round(max(0,self.until-now),1),'sent':self.sent,'deferred':self.deferred,
                    'http_429_count':self.rate_limited,'last_429_epoch':self.last_429}
