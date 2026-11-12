# HYPE asymmetric loss-cut / winner-run audit — 2026-11-12
Research / paper only.

## Frozen entry
Use the previously frozen post-local entry rule. Do not change entry thresholds.

## Objective
Keep winning trades alive; reduce losing trades without using a tight MFE trail.

## Development selection
Tested fixed adverse-price cuts from 0.4% to 3.0% on Jul12-Aug07 + Aug08-Sep01 only, with 0.15% round-trip cost assumption.
A 1.0% adverse-price cut had the best combined development compound among the tested simple cuts.
It was then left unchanged on sealed May, Sep01-Oct01, and Oct04-Nov03.

## Final loss rule
- LONG after Local Low: stop at 1.00% below entry, unless an existing structural stop is closer.
- SHORT after Local High: stop at 1.00% above entry, unless structural stop is closer.
- No tight profit trail.
- If stop is not hit, hold until causal opposite-Local confirmation in this audit.
- Cost model: 0.15% of notional per complete round trip.

## 67 completed sequential trades
- fixed-cut exits: 22
- positive closed trades after costs: 49.25%
- average winning equity return at 5x: +14.16%
- average losing equity return at 5x: -4.37%
- profit factor on equity-return sums: 3.14
- maximum loss streak: 6

## User-native sizing: 25x instrument leverage x 20% account margin = 5x account exposure
Starting equity: $100
- end sealed May: $471.51
- end Jul12-Aug07: $755.20
- end Aug08-Sep01: $583.32
- end Sep01-Oct01: $1,037.06
- end Oct04-Nov03: $1,308.86
- final: $1,308.86
- max closed-equity DD: 29.36%
- worst modeled trade: -5.75% equity including cost assumption

## Lower-DD frontier with exactly the same entry and 1% loss-cut
- 3x exposure: $100 -> $531.16; max DD 18.56%; worst trade -3.45%
- 4x exposure: $100 -> $848.72; max DD 24.11%; worst trade -4.60%
- 5x exposure: $100 -> $1,308.86; max DD 29.36%; worst trade -5.75%

## Comparison: structural stop only, same fixed 5x exposure
With no 1% early loss-cut, using only the wider structural stop and the same causal exit:
- $100 -> about $2,120.70
- max DD about 49.12%
- worst modeled trade about -17.92% equity

Therefore the 1% cut gives up some terminal compound in exchange for materially smaller single-trade loss and drawdown, while leaving winning positions untrailed.

## Exit headroom / oracle ceiling (NOT tradable backtest)
Keeping the same 1% stop and fixed 5x exposure, but exiting surviving trades exactly at the future opposite Local extreme would produce an oracle-only upper bound:
- $100 -> about $15,540.70
- max closed-equity DD about 21.09%
This is not implementable because the exact opposite Local extreme is only known afterward. It quantifies that the main remaining opportunity is exit / MFE retention, not more entry leverage.

## Verdict
Promotable research candidate for the loss side: 1% adverse-price cut, no tight profit trail.
The remaining bottleneck is causal exit timing. Do not increase leverage to compensate for MFE giveback; improve the opposite-local / control-transfer exit detector instead.


## Additional exit/pyramiding challenges (rejected)
After freezing the 1% loss-cut, additional causal overlays were challenged:
- flow + MFE giveback exit;
- H1 opposite candidate K0/K1 exits;
- K0/K1 allowed only after material MFE;
- simple profit-only pyramiding with rung stops.

None produced a better transferable full-history compound than the plain 1% loss-cut + winner-run baseline at the same 5x account exposure. The best-looking development exits either clipped May/Oct-Nov or reduced total compound. Therefore they are not promoted.

Current best robust 5x baseline remains:
- $100 -> $1,308.86
- max closed-equity DD 29.36%
- worst modeled trade -5.75%
- no tight profit trail
- 1% adverse price loss-cut
- causal opposite-Local exit until a better OOS-stable MFE/exit detector is found.
