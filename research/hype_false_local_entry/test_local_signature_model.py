import unittest
from types import SimpleNamespace

from research.hype_false_local_entry.local_signature_model import LocalSignatureModel


class LocalSignatureModelTest(unittest.TestCase):
    def test_no_time_gate_blocks_a_high_score(self):
        m=LocalSignatureModel(low_threshold=0.5,high_threshold=0.5)
        # Seed a simple separable state; decision has no checkpoint/age argument.
        for _ in range(20):
            m.learn("LOW",{"x":1.0},True)
            m.learn("LOW",{"x":-1.0},False)
        d=m.decide(
            side="LOW",ts_ms=1,candidate_id="L-1",extreme_price=100,
            mark_price=100.1,features={"x":1.0},seen_input_ids=set(range(1,117)),
            quality_ok=True,decisive_evidence={}
        )
        self.assertNotIn("checkpoint",d.__dict__)
        self.assertTrue(d.score>=0.0)

    def test_invalidated_candidate_cannot_enter(self):
        m=LocalSignatureModel(low_threshold=0.0,high_threshold=0.0)
        d=m.decide(
            side="HIGH",ts_ms=1,candidate_id="H-1",extreme_price=100,
            mark_price=99.9,features={"x":1.0},seen_input_ids=set(),
            quality_ok=True,decisive_evidence={},invalidated=True
        )
        self.assertFalse(d.enter)
        self.assertEqual(d.state,"INVALIDATED")


if __name__=="__main__":
    unittest.main()
