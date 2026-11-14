"""Research-only deterministic risk sizing and execution stress, not historical fills.
Run: python research/hype_terminal_local_strategy/stop_risk_stress_20261114.py
"""
import json

def size(equity, risk_fraction, stop_fraction, fee_fraction, gap_fraction, max_exposure=5):
    assert equity > 0 and 0 < risk_fraction <= .01
    assert stop_fraction > 0 and fee_fraction >= 0 and gap_fraction >= 0
    loss_fraction = stop_fraction + fee_fraction + gap_fraction
    notional = min(equity * risk_fraction / loss_fraction, equity * max_exposure)
    return dict(notional=round(notional, 6), exposure=round(notional / equity, 6),
                stress_loss=round(notional * loss_fraction, 6),
                risk_pct=round(100 * notional * loss_fraction / equity, 6))

def main():
    rows=[]
    for stop in (.01, .0314):
        for gap in (0, .005, .01, .025):
            for risk in (.0025, .005):
                rows.append(dict(stop_pct=100*stop,gap_pct=100*gap,
                                 target_risk_pct=100*risk,
                                 **size(100,risk,stop,.0015,gap)))
    assert size(100,.005,.01,.0015,.01)["exposure"] == .232558
    assert size(100,.0025,.01,.0015,.01)["stress_loss"] == .25
    assert all(row["risk_pct"] <= row["target_risk_pct"]+1e-6 for row in rows)
    print(json.dumps(rows,indent=2))
if __name__ == "__main__":
    main()
