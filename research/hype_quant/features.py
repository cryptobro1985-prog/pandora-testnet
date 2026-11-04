from __future__ import annotations
from collections import deque
import math
import statistics
from typing import Any


def finite(v):
    return isinstance(v,(int,float)) and math.isfinite(v)


class FeatureState:
    """Causal feature merger for 1s microstructure + latest 1m context."""
    def __init__(self):
        self.context={}
        self.prices=deque()
        self.last_ts_ms=None
        self.last_price=None

    def update_context(self,row:dict[str,Any]):
        if isinstance(row,dict) and "error" not in row:
            self.context=row

    def _price_at_or_before(self,target_ms:int):
        for ts,p in reversed(self.prices):
            if ts<=target_ms:
                return p
        return None

    def update_micro(self,row:dict[str,Any])->tuple[float,dict[str,float]]:
        ts=int(row.get("ts_ms") or 0)
        price=row.get("mid")
        if not finite(price) or price<=0:
            price=row.get("best_bid")
        if not finite(price) or price<=0:
            raise ValueError("micro row has no valid price")
        price=float(price)
        self.prices.append((ts,price))
        cutoff=ts-20*60*1000
        while self.prices and self.prices[0][0]<cutoff:
            self.prices.popleft()

        x={}
        direct_keys=(
            "spread_bps","book_imbalance_5","book_imbalance_25",
            "bid_depth_5","ask_depth_5","bid_depth_25","ask_depth_25",
            "flow_imbalance_5s","flow_imbalance_15s","flow_imbalance_60s",
            "buy_notional_60s","sell_notional_60s",
            "long_liq_notional_5s","short_liq_notional_5s",
            "long_liq_notional_15s","short_liq_notional_15s",
            "long_liq_notional_60s","short_liq_notional_60s",
            "open_interest","oi_change_since_prev_poll_pct",
            "ask_replenishment_proxy_ratio_60s","bid_replenishment_proxy_ratio_60s",
            "book_invalidations","channel_coverage_seconds",
        )
        for k in direct_keys:
            v=row.get(k)
            if finite(v):x[k]=float(v)

        for sec in (5,15,30,60,180,300):
            old=self._price_at_or_before(ts-sec*1000)
            if old and old>0:
                x[f"ret_{sec}s"]=price/old-1.0

        # 60s realized one-second log-return volatility.
        recent=[(t,p) for t,p in self.prices if t>=ts-60_000]
        if len(recent)>=3:
            rs=[]
            for (_,a),(_,b) in zip(recent,recent[1:]):
                if a>0 and b>0:rs.append(math.log(b/a))
            if len(rs)>=2:x["vol_60s"]=statistics.pstdev(rs)

        for n in (5,25):
            b=x.get(f"bid_depth_{n}"); a=x.get(f"ask_depth_{n}")
            if finite(b) and finite(a) and b>0 and a>0:
                x[f"depth_log_ratio_{n}"]=math.log(b/a)

        lng=x.get("long_liq_notional_60s",0.0); sht=x.get("short_liq_notional_60s",0.0)
        den=lng+sht
        if den>0:x["liq_imbalance_60s"]=(sht-lng)/den

        c=self.context
        for k in ("basis_bps","long_short_holder_ratio","funding_rate","runner_clock_offset_ms"):
            v=c.get(k)
            if finite(v):x[k]=float(v)

        oi_notional=c.get("oi_notional")
        if finite(oi_notional) and oi_notional>0:
            x["log_oi_notional"]=math.log1p(float(oi_notional))

        for label,key in (
            ("60m_high","rolling_60m_high"),("60m_low","rolling_60m_low"),
            ("6h_high","rolling_6h_high"),("6h_low","rolling_6h_low"),
            ("24h_high","rolling_24h_high"),("24h_low","rolling_24h_low"),
        ):
            level=c.get(key)
            if finite(level) and level>0:
                x[f"dist_{label}"]=price/float(level)-1.0

        # Absolute notionals/depth vary by regime; logs make them learnable.
        for k in list(x):
            if k.endswith("_notional_60s") or k.startswith(("bid_depth_","ask_depth_")):
                v=x[k]
                if v>=0:x["log_"+k]=math.log1p(v)

        self.last_ts_ms=ts; self.last_price=price
        return price,x
