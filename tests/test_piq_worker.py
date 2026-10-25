"""Deterministic worker tests: no network, database or wall-clock sleeps."""
import concurrent.futures
import copy
import datetime
import unittest
from unittest.mock import patch

import app
from source_health import LatencyMetrics


def iso(epoch):
    return datetime.datetime.fromtimestamp(epoch,datetime.timezone.utc).isoformat()


class ClockStop:
    def __init__(self,duration):
        self.clock=0.;self.duration=duration;self.status=[]

    def is_set(self):
        return self.clock>=self.duration

    def wait(self,seconds):
        self.status.append(copy.deepcopy(app.S.get("sources",{}).get("PiQDirect",{})))
        self.clock=round(self.clock+max(.001,seconds),6)


class ImmediatePool:
    pools=[]

    def __init__(self,**kwargs):
        self.kwargs=kwargs;self.pools.append(self)

    def submit(self,fn,*args,**kwargs):
        future=concurrent.futures.Future()
        try:future.set_result(fn(*args,**kwargs))
        except Exception as exc:future.set_exception(exc)
        return future

    def shutdown(self,**kwargs):
        pass


class PiQWorkerTests(unittest.TestCase):
    def setUp(self):
        self.saved=copy.deepcopy(app.S);app.S.update(engine_active=True,sources={},errors=0)
        ImmediatePool.pools=[]

    def tearDown(self):
        app.S.clear();app.S.update(self.saved)

    def run_worker(self,fetch,discover=None,ingest=None,duration=20,start=1000):
        stop=ClockStop(duration)
        row={"url":"https://piqmarkets.com/story/test","headline_hint":"Bitcoin ETF approved"}
        discover=discover or (lambda **kwargs:[row])
        ingest=ingest or (lambda *args:True)
        with patch.object(app,"SHUTDOWN",stop),patch.object(app,"START",start),\
             patch.object(app.time,"time",side_effect=lambda:1000+stop.clock),\
             patch.object(app.time,"monotonic",side_effect=lambda:stop.clock),\
             patch.object(app,"LATENCIES",LatencyMetrics()),\
             patch.object(app.concurrent.futures,"ThreadPoolExecutor",ImmediatePool),\
             patch.object(app,"piq_discover",side_effect=discover) as discovery,\
             patch.object(app,"piq_fetch_story",side_effect=fetch) as fetched,\
             patch.object(app,"ingest_event",side_effect=ingest) as ingested,\
             patch.object(app,"journal"):
            app.piq_direct_realtime()
        return stop,fetched,ingested,discovery

    def story(self,url="https://piqmarkets.com/story/test",created=1000):
        return {"url":url,"text":"Bitcoin ETF approved","created_at":iso(created)}

    def test_transient_fetch_failure_is_retried_then_ingested_once(self):
        outcomes=[RuntimeError("temporary"),self.story()]
        def fetch(*args,**kwargs):
            result=outcomes.pop(0)
            if isinstance(result,Exception):raise result
            return result
        stop,fetched,ingested,_=self.run_worker(fetch)
        self.assertEqual(fetched.call_count,2);self.assertEqual(ingested.call_count,1)
        self.assertEqual(stop.status[-1]["story_retries_total"],1)
        self.assertEqual(stop.status[-1]["exhausted_stories_total"],0)

    def test_fetch_failure_has_three_attempt_limit(self):
        def fetch(*args,**kwargs):raise RuntimeError("blocked")
        stop,fetched,ingested,_=self.run_worker(fetch,duration=35)
        self.assertEqual(fetched.call_count,3);ingested.assert_not_called()
        self.assertEqual(stop.status[-1]["exhausted_stories_total"],1)
        self.assertEqual(stop.status[-1]["pending_stories"],0)

    def test_ingestion_error_is_visible_and_retried_with_same_id(self):
        attempts=[]
        def ingest(*args):
            attempts.append(args[0])
            if len(attempts)==1:raise RuntimeError("temporary database outage")
            return True
        stop,fetched,ingested,_=self.run_worker(lambda *a,**k:self.story(),ingest=ingest)
        self.assertEqual(fetched.call_count,1);self.assertEqual(ingested.call_count,2)
        self.assertEqual(attempts[0],attempts[1])
        self.assertEqual(stop.status[-1]["ingestion_errors_total"],1)
        self.assertTrue(any(s.get("last_ingest_error") for s in stop.status))

    def test_startup_only_resolves_eight_and_never_trades_old_pages(self):
        rows=[{"url":"https://piqmarkets.com/story/test-"+str(i)} for i in range(20)]
        stop,fetched,ingested,_=self.run_worker(lambda url,*a,**k:self.story(url,999),discover=lambda **k:rows)
        self.assertEqual(fetched.call_count,8);ingested.assert_not_called()
        self.assertEqual(stop.status[-1]["startup_old_filtered"],8)
        self.assertFalse(stop.status[-1]["realtime_verified"])

    def test_pending_completions_do_not_wait_another_poll_per_stage(self):
        times=[]
        def ingest(*args):times.append(app.time.monotonic());return True
        self.run_worker(lambda *a,**k:self.story(),ingest=ingest,duration=2)
        self.assertEqual(len(times),1);self.assertLess(times[0],1.)

    def test_realtime_is_based_on_p95_not_fastest_story(self):
        rows=[{"url":"https://piqmarkets.com/story/fast"},{"url":"https://piqmarkets.com/story/slow"}]
        def fetch(url,*a,**k):return self.story(url,1000 if url.endswith("fast") else 980)
        stop,_,_,_=self.run_worker(fetch,discover=lambda **k:rows,start=900,duration=2)
        final=stop.status[-1]
        self.assertEqual(final["delivery"]["samples"],2)
        self.assertGreater(final["delivery"]["p95_seconds"],10)
        self.assertFalse(final["realtime_verified"])

    def test_story_and_ingestion_queues_stay_bounded(self):
        rows=[{"url":"https://piqmarkets.com/story/test-"+str(i)} for i in range(100)]
        def discover(**kwargs):return [] if app.time.monotonic()<5 else rows
        stop,_,_,_=self.run_worker(lambda url,*a,**k:self.story(url,1005),discover=discover,duration=7)
        self.assertLessEqual(max(s.get("pending_stories",0) for s in stop.status),32)
        self.assertLessEqual(max(s.get("fetches_inflight",0) for s in stop.status),16)
        self.assertLessEqual(max(s.get("ingestions_inflight",0) for s in stop.status),16)
        self.assertEqual([p.kwargs["max_workers"] for p in ImmediatePool.pools],[4,2])


if __name__=="__main__":unittest.main()
