"""Measured delivery and processing latency, separate from transport health."""
from collections import defaultdict, deque
import math
import threading


class LatencyMetrics:
    def __init__(self, capacity=256, window=1800):
        self.capacity = capacity
        self.window = window
        self.rows = defaultdict(lambda: deque(maxlen=capacity))
        self.lock = threading.Lock()

    def record(self, key, seconds, observed_at):
        if not all(math.isfinite(x) for x in (seconds, observed_at)) or seconds < 0:
            return
        with self.lock:
            self.rows[key].append((observed_at, seconds))

    def summary(self, key, epoch, realtime_limit=10):
        with self.lock:
            samples = [(t, v) for t, v in self.rows.get(key, ())
                       if 0 <= epoch-t <= self.window]
        values = sorted(v for _, v in samples)
        def quantile(q):
            return round(values[max(0, math.ceil(len(values)*q)-1)], 4) if values else None
        return {"samples": len(values), "p50_seconds": quantile(.5),
                "p95_seconds": quantile(.95), "max_seconds": max(values) if values else None,
                "last_observed_epoch": samples[-1][0] if samples else None,
                "realtime_verified": bool(values and quantile(.95) <= realtime_limit),
                "measurement_window_seconds": self.window}

    def snapshot(self, epoch):
        with self.lock:
            keys = list(self.rows)
        return {key: self.summary(key, epoch) for key in keys}


def aggregate_delivery(status):
    """All active accounts need evidence; a successful GET is never evidence."""
    values = list(status.values())
    verified = sum(bool(v.get("ok") and v.get("delivery", {}).get("realtime_verified")) for v in values)
    return {"realtime_verified": bool(values and verified == len(values)),
            "realtime_accounts_verified": verified,
            "realtime_accounts_unverified": len(values)-verified}
