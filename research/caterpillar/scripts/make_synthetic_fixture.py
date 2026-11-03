"""Deterministic offline CLI fixture. This is NOT market evidence or an evaluation sample."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from caterpillar.model import SYMBOLS, Trade


def generate(path):
    path = Path(path)
    if path.exists():
        raise SystemExit('Refusing to overwrite '+str(path))
    with path.open('w') as output:
        counter = 0
        for symbol in SYMBOLS:
            price, ts = 100.0, 1700000000.0
            current_hour = int(ts//3600)*3600
            long_context = SYMBOLS.index(symbol) % 2 == 0
            prior = [(100, 110+i, 90+i, 100) for i in range(4)] if long_context else [(100, 110-i, 90-i, 100) for i in range(4)]
            prior += [(100, 105, 85, 90), (90, 104, 86, 100)] if long_context else [(100, 120, 95, 110), (110, 119, 96, 100)]
            for hour, (opened, high, low, closed) in enumerate(prior):
                start = current_hour-(6-hour)*3600
                candle = {'open_ts': start, 'available_ts': start+3600, 'open': opened,
                          'high': high, 'low': low, 'close': closed, 'volume': 1000,
                          'interval_minutes': 60}
                output.write(json.dumps({'event': 'H1_SEED', 'symbol': symbol, 'candle': candle, 'as_of': ts})+'\n')
            blocks = [(-1, .85)]*10
            for _ in range(3):
                blocks += [(1, x) for x in (.58, .7, .82, .9, .96, .98)]
                blocks += [(-1, x) for x in (.58, .7, .82, .9, .96, .98)]
            for direction, dominance in blocks:
                for i in range(32):
                    counter += 1; ts += .1; price *= 1+direction*.0002
                    side = 1 if i % 2 == 0 else -1
                    fraction = dominance if side == direction else 1-dominance
                    t = Trade(symbol, ts, price, fraction*20, side, str(counter))
                    output.write(json.dumps(asdict(t))+'\n')
    print('Synthetic fixture only:', path)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python scripts/make_synthetic_fixture.py OUTPUT.jsonl')
    generate(sys.argv[1])
