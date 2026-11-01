"""Bounded, prioritized H1/M15 bootstrap; read-only public exchange requests.

Selected and retained markets have their own worker slots. A slow background
candidate cannot leave the current five waiting behind an old captured list.
"""
from concurrent.futures import ThreadPoolExecutor
import copy
import threading
import time


class RateLimiter:
    """A shared request-start limiter, also interruptible during shutdown."""
    def __init__(self, requests_per_second=5, clock=time.monotonic):
        if requests_per_second<=0:raise ValueError('request rate must be positive')
        self.interval=1./float(requests_per_second)
        self.clock=clock;self.lock=threading.Lock();self.next_allowed=0.

    def acquire(self, stop):
        if stop.is_set():return False
        with self.lock:
            now=self.clock()
            target=max(now,self.next_allowed)
            self.next_allowed=target+self.interval
        return not stop.wait(max(0.,target-now))


class HistoryBootstrap:
    def __init__(self, stop, fetch_history, accept_candles, checkpoint, report,
                 needs_history, selected_symbols, retained_symbols, candidate_symbols,
                 *, selected_workers=5, background_workers=1, requests_per_second=5,
                 poll_interval=.2, retry_min=5., retry_max=30.):
        if not 1<=selected_workers<=5 or not 0<=background_workers<=1:
            raise ValueError('invalid bounded history worker count')
        if poll_interval<=0 or not 0<retry_min<=retry_max:
            raise ValueError('invalid bootstrap timing')
        self.stop=stop;self.fetch_history=fetch_history;self.accept_candles=accept_candles
        self.checkpoint=checkpoint;self.report=report;self.needs_history=needs_history
        self.selected_symbols=selected_symbols;self.retained_symbols=retained_symbols
        self.candidate_symbols=candidate_symbols
        self.selected_workers=selected_workers;self.background_workers=background_workers
        self.requests_per_second=requests_per_second;self.poll_interval=poll_interval
        self.retry_min=retry_min;self.retry_max=retry_max
        self.limiter=RateLimiter(requests_per_second)
        self.lock=threading.RLock();self.checkpoint_lock=threading.Lock();self.states={};self.futures={};self.failures={};self.retry_at={}
        self.started_at=None;self.running=False

    def _publish(self,symbol,phase,**fields):
        with self.lock:
            state={**self.states.get(symbol,{}),'state':phase,'updated_at':time.time(),**fields}
            self.states[symbol]=state
        try:self.report(symbol,copy.deepcopy(state))
        except Exception:
            # An optional status sink must not erase successfully received data.
            # Its failure is visible in the polling snapshot.
            with self.lock:self.states[symbol]['report_error']=True

    def _fetch(self,symbol,lane):
        began=time.time()
        self._publish(symbol,'FETCHING_H1',ok=False,started_at=began,lane=lane,error=None)
        responses=[]
        try:
            for interval,limit in (('1h',120),('15m',48)):
                if not self.limiter.acquire(self.stop):
                    self._publish(symbol,'STOPPED',ok=False,finished_at=time.time())
                    return False
                self._publish(symbol,'FETCHING_H1' if interval=='1h' else 'FETCHING_M15',ok=False)
                rows=self.fetch_history(symbol,interval,limit)
                if not isinstance(rows,(list,tuple)) or not rows:
                    raise RuntimeError('empty_or_invalid_'+interval+'_history')
                responses.append(rows)
                if self.stop.is_set():
                    self._publish(symbol,'STOPPED',ok=False,finished_at=time.time())
                    return False
            # Publish a consistent pair, rather than leaving half of a new
            # bootstrap visible while the second request is still outstanding.
            for rows in responses:self.accept_candles(rows,history=True)
            if self.checkpoint is not None:
                with self.checkpoint_lock:self.checkpoint()
            if self.needs_history(symbol):
                self._publish(symbol,'WAIT_HISTORY',ok=False,finished_at=time.time(),
                              h1_rows=len(responses[0]),m15_rows=len(responses[1]),
                              error='history_insufficient_or_not_current')
                return False
            self._publish(symbol,'HISTORY_READY',ok=True,finished_at=time.time(),
                          h1_rows=len(responses[0]),m15_rows=len(responses[1]),error=None)
            return True
        except Exception as exc:
            self._publish(symbol,'HISTORY_FAILED',ok=False,finished_at=time.time(),
                          error=type(exc).__name__+':'+str(exc)[:160])
            return False

    def _wanted(self,callback):
        return list(dict.fromkeys(str(s) for s in callback() if s))

    def _eligible(self,symbol):
        if symbol in self.futures or time.monotonic()<self.retry_at.get(symbol,0):return False
        try:return bool(self.needs_history(symbol))
        except Exception as exc:
            self._publish(symbol,'HISTORY_CHECK_FAILED',ok=False,error=type(exc).__name__+':'+str(exc)[:160])
            self.retry_at[symbol]=time.monotonic()+self.retry_min
            return False

    def run(self):
        with self.lock:
            self.started_at=time.time();self.running=True
        foreground=ThreadPoolExecutor(max_workers=self.selected_workers,thread_name_prefix='selected-history')
        background=ThreadPoolExecutor(max_workers=max(1,self.background_workers),thread_name_prefix='candidate-history')
        try:
            while not self.stop.is_set():
                for symbol,(future,lane) in list(self.futures.items()):
                    if not future.done():continue
                    try:success=bool(future.result())
                    except Exception as exc:
                        self._publish(symbol,'HISTORY_FAILED',ok=False,error=type(exc).__name__+':'+str(exc)[:160])
                        success=False
                    self.futures.pop(symbol,None)
                    if success:
                        self.failures.pop(symbol,None);self.retry_at.pop(symbol,None)
                    else:
                        count=self.failures.get(symbol,0)+1;self.failures[symbol]=count
                        self.retry_at[symbol]=time.monotonic()+min(self.retry_max,self.retry_min*2**min(count-1,8))
                # Re-read the current priority on every scheduling pass. There
                # are never dozens of obsolete candidates queued in an executor.
                selected=self._wanted(self.selected_symbols)
                retained=self._wanted(self.retained_symbols)
                priority=list(dict.fromkeys(selected+retained))
                priority_set=set(priority)
                occupied=sum(lane=='selected' for _,lane in self.futures.values())
                for symbol in priority:
                    if occupied>=self.selected_workers:break
                    if not self._eligible(symbol):continue
                    self.futures[symbol]=(foreground.submit(self._fetch,symbol,'selected'),'selected')
                    occupied+=1
                occupied=sum(lane=='background' for _,lane in self.futures.values())
                if self.background_workers:
                    for symbol in self._wanted(self.candidate_symbols):
                        if occupied>=self.background_workers:break
                        if symbol in priority_set or not self._eligible(symbol):continue
                        self.futures[symbol]=(background.submit(self._fetch,symbol,'background'),'background')
                        occupied+=1
                self.stop.wait(self.poll_interval)
        finally:
            # Only these explicitly-owned workers are joined. Individual public
            # requests have their own bounded timeout in the supplied fetcher.
            foreground.shutdown(wait=True,cancel_futures=True)
            background.shutdown(wait=True,cancel_futures=True)
            with self.lock:self.running=False

    def snapshot(self):
        with self.lock:
            return dict(started_at=self.started_at,running=self.running,
                        symbols=copy.deepcopy(self.states),
                        active=[symbol for symbol,(future,_) in list(self.futures.items()) if not future.done()],
                        workers=dict(selected=self.selected_workers,background=self.background_workers),
                        requests_per_second=self.requests_per_second)
