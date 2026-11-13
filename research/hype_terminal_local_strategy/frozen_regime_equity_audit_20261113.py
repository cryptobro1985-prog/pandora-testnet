"""Research-only audit of REAL REPORTED frozen HYPE regime equity checkpoints.
This is NOT per-trade replay. Inputs copied verbatim from 2026-11-12 frozen
HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md; no synthetic fills.
"""
from decimal import Decimal
PERIODS = ["sealed May", "Jul12-Aug07", "Aug08-Sep01", "Sep01-Oct01", "Oct04-Nov03"]
EQUITY = list(map(Decimal, ["100", "471.51", "755.20", "583.32", "1037.06", "1308.86"]))
def audit():
    out = []
    peak = EQUITY[0]
    for i, period in enumerate(PERIODS, 1):
        ret = (EQUITY[i] / EQUITY[i-1] - 1) * 100
        peak = max(peak, EQUITY[i])
        dd = (1 - EQUITY[i]/peak)*100
        out.append((period, round(ret,2), round(dd,2)))
    return out
if __name__ == "__main__":
    for row in audit(): print(row)
    assert len(audit()) == 5
    assert audit()[2][1] == Decimal("-22.76")
    assert audit()[-1][1] == Decimal("26.21")
