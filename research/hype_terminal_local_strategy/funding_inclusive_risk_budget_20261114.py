#!/usr/bin/env python3
"""Conservative stop-risk budget sensitivity. Scenarios, NOT Bybit replay."""
from decimal import Decimal as D
E=D("100")
def notional(risk, stop, fees, slip, funding, reserved=D("0")):
    unit=sum((D(str(v)) for v in (stop,fees,slip,funding)),D("0"))
    assert unit>0 and D(str(risk))>0 and reserved>=0
    return max(D("0"),(E*D(str(risk))-reserved)/unit)
def main():
    print("side,risk,stop,fee,slip,funding,notional,equity_exposure")
    for side in ("LOW_LONG","HIGH_SHORT"):
        for risk in (".0025",".005"):
            for slip in (".005",".01",".025"):
                n=notional(risk,".01",".0015",slip,".0006")
                print(f"{side},{risk},.01,.0015,{slip},.0006,{n:.6f},{n/E:.6f}")
    assert notional(".005",".01",".0015",".005",".0006") < D("30")
    assert notional(".0025",".01",".0015",".005",".0006") < D("15")
    assert notional(".005",".01",".0015",".025",".0006") < D("14")
    print("PASS 3 budget assertions")
if __name__=="__main__": main()
