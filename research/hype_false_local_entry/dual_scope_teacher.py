"""Dual H1 teacher contract for HYPE locals.

INTERNAL_L3_K1 is the broad/tactical teacher: more turns, earlier maturity.
STRICT_L6_K2 is the macro/core teacher: fewer, larger structural turns.

Future H1 bars are used ONLY after they have completed and ONLY to mature a
teacher label.  They are never exposed as detector inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

HOUR_MS = 3_600_000


@dataclass(frozen=True)
class TeacherScope:
    name: str
    lookback: int
    lookahead: int
    role: str

    def maturity_ms(self, hour_ms: int) -> int:
        # Pivot hour itself completes at +1H, then K future completed hours.
        return int(hour_ms) + (self.lookahead + 1) * HOUR_MS


INTERNAL = TeacherScope("INTERNAL_L3_K1", 3, 1, "TACTICAL")
STRICT = TeacherScope("STRICT_L6_K2", 6, 2, "CORE")
SCOPES = {INTERNAL.name: INTERNAL, STRICT.name: STRICT}


def scope(name: str | TeacherScope) -> TeacherScope:
    if isinstance(name, TeacherScope):
        return name
    try:
        return SCOPES[str(name)]
    except KeyError as exc:
        raise ValueError(f"unknown teacher scope: {name}") from exc


def _rows_by_hour(rows: Iterable[Mapping]) -> dict[int, dict]:
    out = {}
    for row in rows:
        h = int(row["start_ms"])
        out[h] = {
            "start_ms": h,
            "high": float(row["high"]),
            "low": float(row["low"]),
        }
    return out


def matured_pivot_label(
    completed_h1_rows: Iterable[Mapping],
    extreme_ts_ms: int,
    side: str,
    teacher_scope: str | TeacherScope,
    now_ms: int,
) -> Optional[bool]:
    """Return None until teacher maturity/data completeness, else bool label."""
    cfg = scope(teacher_scope)
    side = str(side).upper()
    if side not in {"LOW", "HIGH"}:
        raise ValueError("side must be LOW or HIGH")

    hour = (int(extreme_ts_ms) // HOUR_MS) * HOUR_MS
    if int(now_ms) < cfg.maturity_ms(hour):
        return None

    visible=[r for r in completed_h1_rows if int(r["start_ms"])+HOUR_MS<=int(now_ms)]
    by = _rows_by_hour(visible)
    needed = [hour - j * HOUR_MS for j in range(cfg.lookback, 0, -1)]
    needed += [hour]
    needed += [hour + j * HOUR_MS for j in range(1, cfg.lookahead + 1)]
    if any(h not in by for h in needed):
        return None

    row = by[hour]
    past = [by[hour - j * HOUR_MS] for j in range(cfg.lookback, 0, -1)]
    future = [by[hour + j * HOUR_MS] for j in range(1, cfg.lookahead + 1)]

    is_high = row["high"] > max(x["high"] for x in past) and row["high"] >= max(x["high"] for x in future)
    is_low = row["low"] < min(x["low"] for x in past) and row["low"] <= min(x["low"] for x in future)

    # Ambiguous hour ordering is unknowable from H1 OHLC, so it is not a label.
    if is_high and is_low:
        return False
    return bool(is_low if side == "LOW" else is_high)


def collapsed_pivots(
    completed_h1_rows: Iterable[Mapping],
    teacher_scope: str | TeacherScope,
    now_ms: int | None = None,
) -> list[dict]:
    """Causally reproduce alternating terminal-pivot candidates up to now.

    Same-side pivots are collapsed: only the more extreme one survives.  The
    final element is provisional; it is not a finalized Local until an opposite
    matured pivot appears after it.
    """
    cfg=scope(teacher_scope)
    visible=list(completed_h1_rows)
    if now_ms is not None:
        visible=[r for r in visible if int(r["start_ms"])+HOUR_MS<=int(now_ms)]
    rows=sorted(_rows_by_hour(visible).values(),key=lambda x:x["start_ms"])
    raw=[]
    for i in range(cfg.lookback,len(rows)-cfg.lookahead):
        win=rows[i-cfg.lookback:i+cfg.lookahead+1]
        if any(int(b["start_ms"])!=int(a["start_ms"])+HOUR_MS for a,b in zip(win,win[1:])):
            continue
        row=rows[i];past=rows[i-cfg.lookback:i];future=rows[i+1:i+cfg.lookahead+1]
        hi=row["high"]>max(z["high"] for z in past) and row["high"]>=max(z["high"] for z in future)
        lo=row["low"]<min(z["low"] for z in past) and row["low"]<=min(z["low"] for z in future)
        if hi==lo:
            continue
        if not hi and not lo:
            continue
        side="HIGH" if hi else "LOW"
        price=row["high"] if hi else row["low"]
        item={"side":side,"price":price,"hour_ms":int(row["start_ms"]),
              "available_ms":cfg.maturity_ms(int(row["start_ms"]))}
        if raw and raw[-1]["side"]==side:
            better=price>raw[-1]["price"] if side=="HIGH" else price<raw[-1]["price"]
            if better:
                raw[-1]=item
        else:
            raw.append(item)
    return raw


def finalized_terminal_label(
    completed_h1_rows: Iterable[Mapping],
    extreme_ts_ms: int,
    side: str,
    teacher_scope: str | TeacherScope,
    now_ms: int,
) -> Optional[bool]:
    """Label terminal Local only after the next opposite pivot finalizes it.

    Returns:
      None  -> not mature yet OR still the last/provisional pivot;
      False -> candidate hour is not the surviving terminal pivot;
      True  -> candidate hour survived same-side replacement and a later
               opposite pivot has matured, so it is causally finalized.
    """
    cfg=scope(teacher_scope)
    side=str(side).upper()
    if side not in {"LOW","HIGH"}:
        raise ValueError("side must be LOW or HIGH")
    hour=(int(extreme_ts_ms)//HOUR_MS)*HOUR_MS
    if int(now_ms)<cfg.maturity_ms(hour):
        return None

    pivots=collapsed_pivots(completed_h1_rows,cfg,now_ms=now_ms)
    match_index=None
    for i,p in enumerate(pivots):
        if p["hour_ms"]==hour and p["side"]==side:
            match_index=i
            break

    if match_index is None:
        # K bars have already matured.  The hour is either not a pivot or a
        # same-side provisional pivot that was superseded by a better extreme.
        return False

    if match_index==len(pivots)-1:
        # Still provisional.  Do not teach a false "terminal" truth.
        return None

    # A later opposite pivot exists in the collapsed sequence.
    return bool(pivots[match_index+1]["side"]!=side)


def teacher_contract() -> dict:
    return {
        "internal": {
            "name": INTERNAL.name,
            "lookback": INTERNAL.lookback,
            "lookahead": INTERNAL.lookahead,
            "role": INTERNAL.role,
            "rule": "tactical local; may probe/scale but does not authorize full core flip",
        },
        "strict": {
            "name": STRICT.name,
            "lookback": STRICT.lookback,
            "lookahead": STRICT.lookahead,
            "role": STRICT.role,
            "rule": "macro/core local; may authorize core direction change after separate forward gate",
        },
        "future_leakage_guard": "lookahead bars are teacher-only and must be completed before labeling",
        "terminal_finalization": "a pivot stays provisional until a later opposite matured pivot; same-side replacement makes the old provisional false",
    }
