import json
import tempfile
import unittest
from pathlib import Path

from research.hype_local_only.forward_first_signal_audit import audit


class ForwardTeacherScopeTest(unittest.TestCase):
    def test_ttc_strict_scope_uses_only_terminal_strict_labels(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            labels=root/"labels.jsonl"
            events=root/"events.jsonl"
            rows=[
                {"teacher":"STRICT_L6_K2","label":True,"candidate_id":"H-1000",
                 "side":"HIGH","extreme_price":101.0,"extreme_ts_ms":1000,
                 "teacher_finalized_ts_ms":1500},
                {"teacher":"STRICT_L6_K2","label":True,"candidate_id":"L-2000",
                 "side":"LOW","extreme_price":99.0,"extreme_ts_ms":2000,
                 "teacher_finalized_ts_ms":2500},
                {"teacher":"STRICT_L6_K2","label":True,"candidate_id":"H-3000",
                 "side":"HIGH","extreme_price":102.0,"extreme_ts_ms":3000,
                 "teacher_finalized_ts_ms":3500},
                # Tactical teacher must not contaminate strict scoring.
                {"teacher":"INTERNAL_L3_K1","label":True,"candidate_id":"L-1800",
                 "side":"LOW","extreme_price":99.5,"extreme_ts_ms":1800,
                 "teacher_finalized_ts_ms":1900},
            ]
            labels.write_text("\n".join(json.dumps(r) for r in rows)+"\n",encoding="utf-8")
            events.write_text(json.dumps({
                "event":"TTC_SHADOW_SIGNAL",
                "candidate_id":"L-2000","side":"LOW",
                "candidate_ts_ms":2000,"signal_ts_ms":2200,
                "stage":60,
            })+"\n",encoding="utf-8")

            strict=audit(labels,events,event_names="TTC_SHADOW_SIGNAL",
                         actionable=True,teacher_scope="STRICT")
            self.assertEqual(strict["terminal_labels"],3)
            self.assertEqual(strict["metrics"]["episodes"],1)
            self.assertEqual(strict["metrics"]["true_first"],1)
            self.assertEqual(strict["metrics"]["false_first"],0)
            self.assertEqual(strict["teacher"],"STRICT_L6_K2_TERMINAL_FINALIZED")

            internal=audit(labels,events,event_names="TTC_SHADOW_SIGNAL",
                           actionable=True,teacher_scope="INTERNAL")
            self.assertLess(internal["terminal_labels"],strict["terminal_labels"])
            self.assertEqual(internal["metrics"]["true_first"],0)


if __name__=="__main__":
    unittest.main()
