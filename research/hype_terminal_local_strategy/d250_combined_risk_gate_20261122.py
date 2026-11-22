#!/usr/bin/env python3
"""Research-only composition of frozen D250 stop-risk sizing and liquidation clearance.
Fail closed: SIZED alone is not authorization. No real orders.
"""
from dataclasses import dataclass
from d250_conservative_stop_risk_sizer_20261121 import Candidate, size
from d250_liquidation_clearance_research_gate_20261121 import State, gate

def evaluate(candidate: Candidate, state: State):
    """Returns modeled candidate only when both independent gates pass.

    Caller MUST verify current account state, instrument lot/min-notional, actual
    fees/funding, portfolio reservations and executable fills separately.
    """
    if (candidate.side != state.side or candidate.entry != state.entry or
        candidate.stop != state.stop or candidate.liquidation_price != state.liquidation or
        candidate.adverse_gap_fraction != state.gap):
        return {"status": "BLOCK", "reason": "GATE_INPUT_MISMATCH"}
    clearance = gate(state)
    if clearance != "PROVISIONAL_CLEARANCE_ONLY":
        return {"status": "BLOCK", "reason": clearance}
    sizing = size(candidate)
    if sizing["status"] != "SIZED":
        return sizing
    return {"status": "RESEARCH_CANDIDATE_ONLY", "sizing": sizing,
            "clearance": clearance,
            "not_executable": True}

if __name__ == "__main__":
    import unittest
    class T(unittest.TestCase):
        def inputs(self, side="LONG", **state_changes):
            stop = 99 if side=="LONG" else 101
            liq = 95 if side=="LONG" else 105
            c = Candidate(side=side,equity=100,entry=100,stop=stop,
                risk_fraction=.005,existing_stop_risk=0,
                round_trip_cost_fraction=.0015,adverse_gap_fraction=.02,
                liquidation_price=liq)
            s = State(side=side,entry=100,stop=stop,liquidation=liq,
                gap=.02,clearance=.005,mark=100,mark_basis_buffer=.001,
                age_seconds=1,max_age_seconds=5,authenticated=True,
                isolated=True,other_positions=0)
            return c, State(**{**s.__dict__, **state_changes})
        def test_long(self):
            c,s=self.inputs()
            self.assertEqual(evaluate(c,s)["status"],"RESEARCH_CANDIDATE_ONLY")
        def test_short(self):
            c,s=self.inputs("SHORT")
            self.assertEqual(evaluate(c,s)["status"],"RESEARCH_CANDIDATE_ONLY")
        def test_stale(self):
            c,s=self.inputs(age_seconds=9)
            self.assertEqual(evaluate(c,s)["status"],"BLOCK")
        def test_near_liquidation(self):
            c,s=self.inputs(liquidation=96.99)
            self.assertEqual(evaluate(c,s)["reason"],"GATE_INPUT_MISMATCH")
        def test_portfolio(self):
            c,s=self.inputs(other_positions=1)
            self.assertEqual(evaluate(c,s)["status"],"BLOCK")
        def test_untrusted(self):
            c,s=self.inputs(authenticated=False)
            self.assertEqual(evaluate(c,s)["status"],"BLOCK")
        def test_input_mismatch(self):
            c,s=self.inputs(gap=.01)
            self.assertEqual(evaluate(c,s)["reason"],"GATE_INPUT_MISMATCH")
    unittest.main(verbosity=2)
