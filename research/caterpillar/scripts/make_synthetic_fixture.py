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
