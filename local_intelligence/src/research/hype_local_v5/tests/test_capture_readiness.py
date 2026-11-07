import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research.hype_local_v5.resilient_capture import capture_evidence


class CaptureReadinessTests(unittest.TestCase):
    def test_worker_files_and_heartbeats_do_not_establish_market_readiness(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "HYPE_live_raw_frames.jsonl").write_text(json.dumps({"raw_text": '{"op":"pong"}'}) + '\n')
            (root / "HYPE_live_microstructure_1s.jsonl").write_text('{"ts_ms":1,"mid":null}\n')
            (root / "HYPE_market_context.jsonl").write_text('{"errors":["network unavailable"]}\n')
            self.assertFalse(capture_evidence(root)["usable"])

    def test_actual_channel_observations_are_required_even_after_a_corrupt_row(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "HYPE_live_raw_frames.jsonl").write_text('broken\n' + json.dumps({"raw_text": json.dumps({
                "topic": "publicTrade.HYPEUSDT", "data": [{"p": "20", "v": "1", "S": "Buy"}]})}) + '\n')
            (root / "HYPE_live_microstructure_1s.jsonl").write_text('{"ts_ms":1,"mid":20}\n')
            self.assertFalse(capture_evidence(root)["usable"])
            (root / "HYPE_market_context.jsonl").write_text('{"candles":{"60":[{"start_ms":1,"close":20}]}}\n')
            result = capture_evidence(root)
            self.assertTrue(result["usable"])
            self.assertEqual(result["malformed_rows"], 1)
