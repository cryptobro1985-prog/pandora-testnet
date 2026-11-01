"""RAW FLOW recorder: accepted ticks, dedup, bounded queues and persisted gaps."""
import os
from pathlib import Path
import time
import unittest
import uuid

from pandora_raw_flow_recorder import RawFlowRecorder,raw_trade_page,capture_event_page

def raw(n,symbol="TESTRAW"):
    return {"coin":symbol,"tid":f"bybit:{n}","time":1793547000000+n*5,
            "px":"1.125","sz":"20","side":"B" if n%2 else "A"}

class RecorderContracts(unittest.TestCase):
    def test_accepted_trade_preserves_event_and_receive_timestamp(self):
        item=RawFlowRecorder._event_row(raw(5),1793547001.123,"trade-1",55)
        self.assertEqual(item[0],"TESTRAW")
        self.assertEqual(item[1],"bybit:5")
        self.assertEqual(item[2],1793547000025)
        self.assertEqual(item[3],1793547001123)
        self.assertEqual(item[4],"B")
        self.assertEqual(item[7],22.5)
        self.assertEqual(item[8],55)

    def test_full_queue_is_explicitly_reported_and_not_hidden(self):
        recorder=RawFlowRecorder(None,capacity=1)
        recorder.ingest([raw(1),raw(2)],1793547002,"trade-0")
        state=recorder.status()
        self.assertEqual(state["received"],2)
        self.assertEqual(state["queued"],1)
        self.assertEqual(state["dropped"],1)
        self.assertFalse(state["capture_complete"])
        self.assertEqual(recorder.events.qsize(),1)

    def test_invalid_row_is_not_reconstructed(self):
        recorder=RawFlowRecorder(None)
        bad=raw(1);bad["px"]="-1"
        recorder.ingest([bad],1793547002,"trade-0")
        self.assertEqual(recorder.queue.qsize(),0)
        self.assertEqual(recorder.events.qsize(),1)

    def test_no_trading_engine_dependency(self):
        import pandora_raw_flow_recorder as mod
        self.assertFalse(hasattr(mod,"pandora_open"))
        self.assertFalse(hasattr(mod,"pandora_close"))

    def test_persistent_unique_exchange_trade_id(self):
        bound=os.getenv("PANDORA_TEST_DATABASE_URL_FILE")
        if not bound or not Path(bound).is_file():
            self.skipTest("isolated Postgres not provided")
        dsn=Path(bound).read_text().strip()
        if dsn!=os.getenv("DATABASE_URL"):
            self.skipTest("isolated DB binding does not match DATABASE_URL")
        import psycopg
        from psycopg.rows import dict_row
        def connect():
            return psycopg.connect(dsn,autocommit=True,row_factory=dict_row)
        rec=RawFlowRecorder(connect)
        rec.migrate()
        symbol="RAW"+uuid.uuid4().hex[:12].upper()
        entries=[rec._event_row(raw(1,symbol),1793547002,"trade-0"),
                 rec._event_row(raw(2,symbol),1793547002,"trade-0")]
        rec._persist(entries)
        rec._persist(entries)
        with connect() as db:
            row=db.execute("select count(*) n,sum(notional) total from pandora_flow_raw_trades where symbol=%s",(symbol,)).fetchone()
            self.assertEqual(row["n"],2)
            self.assertAlmostEqual(row["total"],45.0)
            db.execute("delete from pandora_flow_raw_trades where symbol=%s",(symbol,))
        self.assertEqual(rec.status()["db_duplicates"],2)

if __name__=="__main__":unittest.main()
