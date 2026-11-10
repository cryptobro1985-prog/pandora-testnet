# HYPE Movement Signature — common-causal chronological replay

No Local labels were used as predictors or entry gates.
Frozen parameters were tuned on Aug08-Sep01 only: {"entry": 0.0025, "edge": 0.001, "giveback_abs": 0.0015, "giveback_frac": 0.55, "min_hold": 2}

## Frozen-model transfer
- DEV_JUL12_AUG07: return 128.77%, maxDD 0.87%, trades 75, trades/day 2.97, win 88.00%, PF 179.56, median MFE capture 85.45%, median giveback 0.22%.
- VAL_AUG08_SEP01: return -10.84%, maxDD 14.19%, trades 73, trades/day 3.04, win 52.05%, PF 0.57, median MFE capture 31.58%, median giveback 0.39%.
- TEST_SEP01_OCT01: return -10.46%, maxDD 11.23%, trades 35, trades/day 1.17, win 20.00%, PF 0.17, median MFE capture 1.47%, median giveback 0.49%.
- HOLDOUT_OCT04_NOV03: return -22.70%, maxDD 23.29%, trades 64, trades/day 2.13, win 31.25%, PF 0.23, median MFE capture 2.81%, median giveback 0.36%.

## Test+holdout leverage overlay
- 1x leverage / 20% margin: equity x0.931, maxDD 7.08%, approx liquidation events 0.
- 5x leverage / 20% margin: equity x0.692, maxDD 31.31%, approx liquidation events 0.
- 10x leverage / 20% margin: equity x0.482, maxDD 52.56%, approx liquidation events 1.
- 25x leverage / 20% margin: equity x0.183, maxDD 82.40%, approx liquidation events 3.

## Statistical status
This is a research replay. Thresholds were tuned only on the validation block, but model/feature design remains researcher-selected. Forward full-116 shadow validation is required before any production claim.
