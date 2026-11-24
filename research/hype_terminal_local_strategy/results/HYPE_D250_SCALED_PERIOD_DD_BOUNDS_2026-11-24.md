# D250 scaled period and closed DD bounds — 2026-11-24
Source HYPE_ASYMMETRIC_RISK_FINAL_2026-11-12.md blob be76b9a61c86ec59c94b885eea4b15ee97cc1c05. Same 67 sequential modeled trades, 34 nonpositive, average loss .0437, maximum .0575 at 5x. No new fills or detector changes.
For scaling k=r/.0575, concavity of log gives log(1+k*x)>=k*log(1+x), so each original period growth factor G implies scaled factor >= G^k, even for negative periods. This is a lower bound, not exact period equity. Any closed drawdown is bounded by all losing trades compounded without winners; chord bound gives DD <= 1-exp(34*.0437/.0575*log(1-r)). Rounded source inputs imply approximate bounds. Period order: May, Jul12-Aug07, Aug08-Sep01, Sep01-Oct01, Oct04-Nov03.
Results:
```json
[
  {
    "risk": 0.0025,
    "aggregateClosedDDUpper": 0.06263345646754359,
    "periodGrowthLower": [
      0.0697497985860056,
      0.0206912564659274,
      -0.011165317084529058,
      0.02533335992459662,
      0.010171676513198724
    ]
  },
  {
    "risk": 0.005,
    "aggregateClosedDDUpper": 0.12148656707480443,
    "periodGrowthLower": [
      0.14436463157479928,
      0.041810641025993744,
      -0.022205969863460018,
      0.051308498974262706,
      0.020446816029486392
    ]
  }
]
```
Reproduce with k=r/.0575, G=[471.51/100,755.20/471.51,583.32/755.20,1037.06/583.32,1308.86/1037.06]. These bounds assume linear scaling of original net returns and no changes in execution, funding, order constraints or gaps. No MTM or liquidation inference. Negative period lower bound does not prove scaled period loss. No rejected overlays reinstated. Individual matched event ledger still required.