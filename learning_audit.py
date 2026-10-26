"""Durable decision/audit labels for PAPER learning.

Every candidate decision can be persisted with its rationale, then labeled from
future live marks at 5m/15m/1h/4h without placing a trade. This keeps rejected
signals useful for post-test analysis while remaining execution-free.
"""
import datetime
import json
import math

HORIZONS = (("5m", 300), ("15m", 900), ("1h", 3600), ("4h", 14400))
MAX_AGE_SECONDS = 5 * 3600


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _epoch(value):
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def ensure_schema(conn):
    conn.execute("""create table if not exists decision_learning_log (
        seq bigserial primary key,
        decision_id text not null unique,
        ts text not null,
        strategy text not null,
        symbol text,
        side integer,
        action text not null,
        reason text,
        entry_price double precision,
        score double precision,
        leverage double precision not null default 1,
        features jsonb not null default '{}'::jsonb,
        labels jsonb not null default '{}'::jsonb,
        status text not null default 'PENDING',
        evaluated_at text
    )""")
    conn.execute("create index if not exists decision_learning_strategy_time_idx on decision_learning_log(strategy,ts)")
    conn.execute("create index if not exists decision_learning_status_time_idx on decision_learning_log(status,ts)")
    conn.execute("create index if not exists decision_learning_symbol_time_idx on decision_learning_log(symbol,ts)")


def record_decision(connect, decision_id, strategy, symbol, side, action, reason,
                    entry_price=None, score=None, leverage=1.0, features=None, ts=None):
    if not decision_id:
        return False
    ts = ts or utcnow()
    try:
        side = int(side or 0)
    except (TypeError, ValueError):
        side = 0
    if side not in (-1, 0, 1):
        side = 0
    try:
        entry = float(entry_price) if entry_price is not None else None
        if entry is not None and (not math.isfinite(entry) or entry <= 0):
            entry = None
    except (TypeError, ValueError, OverflowError):
        entry = None
    try:
        lev = float(leverage or 1.0)
        if not math.isfinite(lev) or lev <= 0:
            lev = 1.0
    except (TypeError, ValueError, OverflowError):
        lev = 1.0
    try:
        score_value = float(score) if score is not None else None
        if score_value is not None and not math.isfinite(score_value):
            score_value = None
    except (TypeError, ValueError, OverflowError):
        score_value = None
    labelable = bool(symbol and side in (-1, 1) and entry)
    status = "PENDING" if labelable else "UNLABELABLE"
    payload = json.dumps(features or {}, default=str)
    with connect() as conn:
        ensure_schema(conn)
        conn.execute("""insert into decision_learning_log
            (decision_id,ts,strategy,symbol,side,action,reason,entry_price,score,leverage,features,status,evaluated_at)
            values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
            on conflict(decision_id) do update set
              strategy=excluded.strategy,
              symbol=coalesce(excluded.symbol,decision_learning_log.symbol),
              side=case when excluded.side in (-1,1) then excluded.side else decision_learning_log.side end,
              action=excluded.action,
              reason=coalesce(excluded.reason,decision_learning_log.reason),
              entry_price=coalesce(excluded.entry_price,decision_learning_log.entry_price),
              score=coalesce(excluded.score,decision_learning_log.score),
              leverage=excluded.leverage,
              features=decision_learning_log.features || excluded.features,
              status=case
                when decision_learning_log.status='COMPLETE' then 'COMPLETE'
                when coalesce(excluded.symbol,decision_learning_log.symbol) is not null
                 and coalesce(nullif(excluded.side,0),decision_learning_log.side) in (-1,1)
                 and coalesce(excluded.entry_price,decision_learning_log.entry_price) is not null
                then case when decision_learning_log.status='UNLABELABLE' then 'PENDING' else decision_learning_log.status end
                else decision_learning_log.status end,
              evaluated_at=coalesce(decision_learning_log.evaluated_at,excluded.evaluated_at)""",
            (str(decision_id), ts, str(strategy), symbol, side, str(action), reason,
             entry, score_value, lev, payload, status, ts if status == "UNLABELABLE" else None))
    return True


def update_labels(connect, prices, now_epoch=None, limit=1000):
    now_epoch = float(now_epoch if now_epoch is not None else datetime.datetime.now(datetime.timezone.utc).timestamp())
    clean_prices = {}
    for symbol, value in (prices or {}).items():
        try:
            px = float(value)
            if math.isfinite(px) and px > 0:
                clean_prices[str(symbol)] = px
        except (TypeError, ValueError, OverflowError):
            pass
    if not clean_prices:
        return {"updated": 0, "completed": 0, "pending": 0}
    cutoff = datetime.datetime.fromtimestamp(now_epoch - MAX_AGE_SECONDS, datetime.timezone.utc).isoformat()
    with connect() as conn:
        ensure_schema(conn)
        rows = conn.execute("""select seq,decision_id,ts,symbol,side,entry_price,leverage,labels,status
            from decision_learning_log
            where status in ('PENDING','PARTIAL') and ts >= %s
            order by seq desc limit %s""", (cutoff, int(limit))).fetchall()
        updated = completed = 0
        for row in rows:
            symbol = str(row["symbol"] or "")
            px = clean_prices.get(symbol)
            started = _epoch(row["ts"])
            entry = row["entry_price"]
            side = int(row["side"] or 0)
            if px is None or started is None or not entry or side not in (-1, 1):
                continue
            age = max(0.0, now_epoch - started)
            lev = float(row["leverage"] or 1.0)
            move_pct = side * (px / float(entry) - 1.0) * 100.0
            roe_pct = move_pct * lev
            labels = dict(row["labels"] or {})
            labels["latest"] = {"age_seconds": round(age, 3), "price": px,
                                "return_pct": round(move_pct, 6), "roe_pct": round(roe_pct, 6)}
            labels["mfe_return_pct"] = round(max(float(labels.get("mfe_return_pct", move_pct)), move_pct), 6)
            labels["mae_return_pct"] = round(min(float(labels.get("mae_return_pct", move_pct)), move_pct), 6)
            labels["mfe_roe_pct"] = round(max(float(labels.get("mfe_roe_pct", roe_pct)), roe_pct), 6)
            labels["mae_roe_pct"] = round(min(float(labels.get("mae_roe_pct", roe_pct)), roe_pct), 6)
            for name, seconds in HORIZONS:
                key = "at_" + name
                if age >= seconds and key not in labels:
                    labels[key] = {"age_seconds": round(age, 3), "price": px,
                                   "return_pct": round(move_pct, 6), "roe_pct": round(roe_pct, 6)}
            done = age >= HORIZONS[-1][1] and all(("at_" + name) in labels for name, _ in HORIZONS)
            status = "COMPLETE" if done else "PARTIAL"
            conn.execute("""update decision_learning_log
                set labels=%s::jsonb,status=%s,evaluated_at=%s where seq=%s""",
                (json.dumps(labels, default=str), status, utcnow(), row["seq"]))
            updated += 1
            completed += int(done)
        pending = conn.execute("""select count(*) as n from decision_learning_log
            where status in ('PENDING','PARTIAL')""").fetchone()["n"]
    return {"updated": updated, "completed": completed, "pending": int(pending or 0)}


def summary(connect):
    with connect() as conn:
        ensure_schema(conn)
        row = conn.execute("""select count(*) as total,
            count(*) filter(where status='COMPLETE') as complete,
            count(*) filter(where status in ('PENDING','PARTIAL')) as pending,
            count(*) filter(where action like 'OPENED%%' or action='OPEN') as opened,
            count(*) filter(where action like 'REJECTED%%' or action like 'SKIPPED%%') as rejected
            from decision_learning_log""").fetchone()
    return {k: int(row[k] or 0) for k in ("total", "complete", "pending", "opened", "rejected")}
