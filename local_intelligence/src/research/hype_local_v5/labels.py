"""OFFLINE reference labels. Never import this module into the live detector.

Strict L6/K2 completed-hour pivots, collapsed into alternating extremes.
An hour containing both a HIGH and LOW pivot has unknown OHLC ordering and is
excluded, rather than inventing a sub-hour sequence. Missing hours break labels.
"""
from __future__ import annotations

import math

HOUR = 3_600_000


def completed_hours(rows):
    groups = {}
    for row in rows:
        start = int(row['start_ms'])
        end = int(row.get('bar_end_ms',row['ts_ms']))
        available = int(row['ts_ms'])
        if start < 0 or end <= start or available < end:
            raise ValueError('input bar has invalid physical or availability times')
        prices = [row[name] for name in ('open', 'high', 'low', 'close')]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(v) or v <= 0 for v in prices):
            raise ValueError('input bar has invalid prices')
        if row['low'] > min(row['open'], row['close']) or row['high'] < max(row['open'], row['close']) or row['low'] > row['high']:
            raise ValueError('input bar has inconsistent OHLC')
        hour = start // HOUR * HOUR
        if end > hour + HOUR:
            raise ValueError('input bar crosses hour boundary')
        groups.setdefault(hour, []).append(row)
    result = []
    for hour, items in sorted(groups.items()):
        items.sort(key=lambda item: int(item['start_ms']))
        cursor = hour
        complete = True
        for item in items:
            if int(item['start_ms']) != cursor or item.get('gap', False):
                complete = False
            cursor = int(item.get('bar_end_ms',item['ts_ms']))
        if not complete or cursor != hour + HOUR:
            continue
        high_row = max(items, key=lambda x: x['high'])
        low_row = min(items, key=lambda x: x['low'])
        result.append(dict(start_ms=hour, ts_ms=hour+HOUR,
            open=items[0]['open'], close=items[-1]['close'],
            high=high_row['high'], low=low_row['low'],
            available_at_ms=max(x['ts_ms'] for x in items),
            high_start_ms=high_row['start_ms'], high_end_ms=high_row.get('bar_end_ms',high_row['ts_ms']),
            low_start_ms=low_row['start_ms'], low_end_ms=low_row.get('bar_end_ms',low_row['ts_ms'])))
    return result


def structural_labels(rows, lookback=6, lookahead=2):
    """Return labels and exclusions. Future data is used here ONLY for scoring."""
    if isinstance(lookback, bool) or isinstance(lookahead, bool) or not isinstance(lookback, int) or not isinstance(lookahead, int) or lookback < 1 or lookahead < 1:
        raise ValueError('lookback and lookahead must be positive integer hours')
    hours = completed_hours(rows)
    labels, excluded = [], []
    for i in range(lookback, len(hours)-lookahead):
        window = hours[i-lookback:i+lookahead+1]
        if any(b['start_ms'] != a['ts_ms'] for a,b in zip(window, window[1:])):
            excluded.append(dict(hour_ms=hours[i]['start_ms'], reason='missing_hour'))
            continue
        row = hours[i]
        past, future = hours[i-lookback:i], hours[i+1:i+lookahead+1]
        high = row['high'] > max(x['high'] for x in past) and row['high'] >= max(x['high'] for x in future)
        low = row['low'] < min(x['low'] for x in past) and row['low'] <= min(x['low'] for x in future)
        if high and low:
            excluded.append(dict(hour_ms=row['start_ms'], reason='ambiguous_high_low_order'))
            continue
        if not high and not low:
            continue
        side, field = ('HIGH', 'high') if high else ('LOW', 'low')
        label = dict(label_id=len(labels)+1, side=side, extreme_price=row[field],
            extreme_interval_start_ms=row[field+'_start_ms'],
            extreme_interval_end_ms=row[field+'_end_ms'],
            label_available_ms=max(x['available_at_ms'] for x in window), hour_ms=row['start_ms'])
        if labels and labels[-1]['side'] == side:
            better = label['extreme_price'] > labels[-1]['extreme_price'] if high else label['extreme_price'] < labels[-1]['extreme_price']
            if better:
                label['label_id'] = labels[-1]['label_id']
                labels[-1] = label
        else:
            labels.append(label)
    for i,label in enumerate(labels):
        # A K2 pivot can still extend before an opposite pivot. The terminal
        # collapsed swing has no completed reference boundary and is censored.
        label['reference_finalized'] = i+1<len(labels)
        label['reference_finalized_ms'] = max(label['label_available_ms'], labels[i+1]['label_available_ms']) if i+1<len(labels) else None
    return labels, excluded
