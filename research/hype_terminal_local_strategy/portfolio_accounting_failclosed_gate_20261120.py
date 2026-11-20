"""Research-only fail-closed gate for existing portfolio_accounting_research.evaluate.
Does not modify baseline, detector or orders. This is NOT a fill simulator.
"""
from math import isfinite
from .portfolio_accounting_research import evaluate

def checked_evaluate(trades, start_equity=100.0):
    """Only closed-equity accounting; MTM, liquidations and MFE remain UNKNOWN."""
    if not isinstance(trades, (list, tuple)) or not trades:
        return {"status": "BLOCKED_NO_TRADES"}
    previous_exit = None
    for i, t in enumerate(trades):
        required = ("trade_id", "entry_ts_ms", "exit_ts_ms", "side",
                    "underlying_return_fraction", "account_exposure",
                    "roundtrip_cost_fraction", "funding_fraction",
                    "authorized_notional", "entry_equity",
                    "authorized_stress_loss", "risk_budget_fraction")
        missing = [k for k in required if k not in t or t[k] is None]
        if missing:
            return {"status": "BLOCKED_MISSING_FIELDS", "trade_index": i, "fields": missing}
        try:
            entry, exit_ = int(t["entry_ts_ms"]), int(t["exit_ts_ms"])
            if entry >= exit_ or (previous_exit is not None and entry < previous_exit):
                return {"status": "BLOCKED_TIME_OR_OVERLAP", "trade_index": i}
            previous_exit = exit_
            numbers = [float(t[k]) for k in ("underlying_return_fraction",
                "account_exposure", "roundtrip_cost_fraction", "funding_fraction",
                "authorized_notional", "entry_equity", "authorized_stress_loss",
                "risk_budget_fraction")]
            if not all(isfinite(x) for x in numbers):
                return {"status": "BLOCKED_NONFINITE", "trade_index": i}
            gross, exposure, fee, funding, notional, entry_equity, stress, budget = numbers
            if t["side"] not in ("LONG", "SHORT") or entry_equity <= 0 or notional <= 0 or fee < 0 or exposure <= 0 or stress < 0 or not 0 < budget <= .005:
                return {"status": "BLOCKED_RISK_OR_ECONOMICS", "trade_index": i}
            if abs(exposure - notional/entry_equity) > 1e-7 or stress > entry_equity*budget + 1e-7:
                return {"status": "BLOCKED_AUTHORIZATION_MISMATCH", "trade_index": i}
        except (ValueError, TypeError, OverflowError):
            return {"status": "BLOCKED_INVALID_FIELDS", "trade_index": i}
    # No claim of provenance or fills: these fields are caller-supplied.
    result = evaluate(trades, start_equity=start_equity)
    return {"status": "SCENARIO_CLOSED_ONLY_NOT_EXECUTION_VERIFIED",
            "closed_accounting": result,
            "mtm_dd": None, "liquidations": None, "mfe_retention": None}

def self_test():
    t = dict(trade_id="synthetic_1", entry_ts_ms=1000, exit_ts_ms=2000,
        side="LONG", underlying_return_fraction=.02, account_exposure=.1,
        roundtrip_cost_fraction=.0015, funding_fraction=.0001,
        authorized_notional=10., entry_equity=100.,
        authorized_stress_loss=.3, risk_budget_fraction=.005)
    assert checked_evaluate([t])["status"].startswith("SCENARIO_")
    assert checked_evaluate([{k:v for k,v in t.items() if k!="funding_fraction"}])["status"]=="BLOCKED_MISSING_FIELDS"
    assert checked_evaluate([{**t, "authorized_notional":50.}])["status"]=="BLOCKED_AUTHORIZATION_MISMATCH"
    assert checked_evaluate([t,{**t,"trade_id":"synthetic_2","entry_ts_ms":1500,"exit_ts_ms":2500}])["status"]=="BLOCKED_TIME_OR_OVERLAP"
    assert checked_evaluate([{**t,"authorized_stress_loss":.8}])["status"]=="BLOCKED_AUTHORIZATION_MISMATCH"
    return 5

if __name__ == "__main__":
    # Package import expected; run with python -m research.hype_terminal_local_strategy.portfolio_accounting_failclosed_gate_20261120
    print({"synthetic_tests_passed": self_test()})
