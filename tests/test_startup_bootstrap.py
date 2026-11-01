"""Software-only startup ordering, bounded concurrency and retry contracts."""
import threading
import time
import unittest

from pandora_bootstrap import HistoryBootstrap,RateLimiter


def eventually(predicate,timeout=2):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.005)
    raise AssertionError('bootstrap condition timed out')


class HistoryBootstrapTests(unittest.TestCase):
    def bootstrap(self,fetch,selected,retained=lambda:(),candidates=lambda:(),**kwargs):
        stop=threading.Event();accepted=[];ready=set()
        def accept(rows,history=False):
            self.assertTrue(history);accepted.append(rows)
            if rows[0]['interval']=='15m':ready.add(rows[0]['symbol'])
        worker=HistoryBootstrap(stop,fetch,accept,lambda:None,lambda *a:None,
            lambda s:s not in ready,selected,retained,candidates,
            requests_per_second=1000,poll_interval=.01,retry_min=.05,retry_max=.1,**kwargs)
        thread=threading.Thread(target=worker.run,daemon=True)
        self.addCleanup(stop.set)
        return worker,thread,stop,accepted,ready

    def test_selected_five_start_in_parallel_without_initial_sleep_or_candidate_queue(self):
        lock=threading.Lock();started=set();release=threading.Event()
        def fetch(symbol,interval,limit):
            if interval=='1h':
                with lock:started.add(symbol)
                if not release.wait(2):raise RuntimeError('test release timeout')
            return [dict(symbol=symbol,interval=interval)]
        selected=lambda:['A','B','C','D','E']
        worker,thread,stop,accepted,ready=self.bootstrap(fetch,selected,candidates=lambda:['Z'+str(i) for i in range(100)])
        thread.start()
        try:
            eventually(lambda:set(selected()).issubset(started))
            self.assertLessEqual(len(worker.futures),6)
            self.assertLessEqual(len(started),6)
            release.set();eventually(lambda:set(selected()).issubset(ready))
            self.assertTrue(all(worker.snapshot()['symbols'][s]['state']=='HISTORY_READY' for s in selected()))
        finally:
            release.set();stop.set();thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_blocked_background_cannot_delay_new_selected_market(self):
        background_started=threading.Event();release=threading.Event();selected=[]
        def fetch(symbol,interval,limit):
            if symbol=='SLOW' and interval=='1h':
                background_started.set()
                if not release.wait(2):raise RuntimeError('test release timeout')
            return [dict(symbol=symbol,interval=interval)]
        worker,thread,stop,accepted,ready=self.bootstrap(fetch,lambda:list(selected),candidates=lambda:['SLOW'])
        thread.start()
        try:
            self.assertTrue(background_started.wait(1))
            selected.append('NEW')
            eventually(lambda:'NEW' in ready)
            self.assertNotIn('SLOW',ready)
            self.assertEqual(worker.snapshot()['symbols']['NEW']['lane'],'selected')
        finally:
            release.set();stop.set();thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_failure_retries_only_its_symbol_without_blocking_other_selected_tokens(self):
        attempts={};lock=threading.Lock()
        def fetch(symbol,interval,limit):
            with lock:
                key=(symbol,interval);attempts[key]=attempts.get(key,0)+1
                count=attempts[key]
            if symbol=='BAD' and interval=='1h' and count==1:raise RuntimeError('temporary source failure')
            return [dict(symbol=symbol,interval=interval)]
        worker,thread,stop,accepted,ready=self.bootstrap(fetch,lambda:['BAD','GOOD'],background_workers=0)
        thread.start()
        try:
            eventually(lambda:'GOOD' in ready)
            eventually(lambda:'BAD' in ready)
            self.assertEqual(attempts[('BAD','1h')],2)
            self.assertEqual(attempts[('GOOD','1h')],1)
            self.assertEqual(worker.snapshot()['symbols']['BAD']['state'],'HISTORY_READY')
        finally:stop.set();thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_partial_pair_is_not_published_when_m15_fetch_fails(self):
        attempted=threading.Event()
        def fetch(symbol,interval,limit):
            if interval=='15m':attempted.set();raise RuntimeError('missing M15')
            return [dict(symbol=symbol,interval=interval)]
        worker,thread,stop,accepted,ready=self.bootstrap(fetch,lambda:['A'],background_workers=0)
        thread.start()
        try:
            self.assertTrue(attempted.wait(1))
            eventually(lambda:worker.snapshot()['symbols']['A']['state']=='HISTORY_FAILED')
            self.assertEqual(accepted,[])
            self.assertFalse(ready)
        finally:stop.set();thread.join(3)

    def test_empty_response_does_not_claim_history_readiness_or_spin_without_backoff(self):
        attempts=[]
        def fetch(symbol,interval,limit):attempts.append(symbol);return []
        worker,thread,stop,accepted,ready=self.bootstrap(fetch,lambda:['EMPTY'],background_workers=0)
        thread.start()
        try:
            eventually(lambda:worker.snapshot().get('symbols',{}).get('EMPTY',{}).get('state')=='HISTORY_FAILED')
            self.assertEqual(accepted,[])
            self.assertFalse(ready)
            self.assertEqual(len(attempts),1)
        finally:stop.set();thread.join(3)


class RateLimiterTests(unittest.TestCase):
    def test_request_starts_are_rate_limited_and_shutdown_interruptible(self):
        class FakeStop:
            def __init__(self):self.now=0.;self.stopped=False
            def is_set(self):return self.stopped
            def wait(self,delay):self.now+=delay;return self.stopped
        stop=FakeStop();limiter=RateLimiter(5,clock=lambda:stop.now)
        starts=[]
        for _ in range(4):
            self.assertTrue(limiter.acquire(stop));starts.append(stop.now)
        for a,b in zip(starts,starts[1:]):self.assertAlmostEqual(b-a,.2)
        stop.stopped=True
        self.assertFalse(limiter.acquire(stop))
