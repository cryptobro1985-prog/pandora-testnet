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

    by = _rows_by_hour(completed_h1_rows)
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
    }
