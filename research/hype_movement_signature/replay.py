#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline

PERIODS = [
    ("P1_JUL12_AUG07", "01_JUL12_AUG07_FULL_MICRO/compact_1m.jsonl.gz"),
    ("P2_AUG08_SEP01", "02_AUG08_SEP01/compact_1m.jsonl.gz"),
    ("P3_SEP01_OCT01", "03_SEP01_OCT01/compact_1m.jsonl.gz"),
    ("P4_OCT04_NOV03", "04_OCT04_NOV03/compact_1m.jsonl.gz"),
]
COST = 0.0016
FEATURE_WINDOWS = (1, 3, 5, 10, 15, 30, 60, 120)
TARGET_HORIZONS = (5, 15, 30, 60)


def load_jsonl_gz(path: Path) -> pd.DataFrame:
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return pd.DataFrame(rows).sort_values("ts_ms").drop_duplicates("ts_ms").reset_index(drop=True)


def future_max(s: pd.Series, h: int) -> pd.Series:
    return s.shift(-1).iloc[::-1].rolling(h, min_periods=h).max().iloc[::-1]


def future_min(s: pd.Series, h: int) -> pd.Series:
    return s.shift(-1).iloc[::-1].rolling(h, min_periods=h).min().iloc[::-1]


def log1p_nonneg(s: pd.Series) -> pd.Series:
    return np.log1p(np.maximum(pd.to_numeric(s, errors="coerce"), 0.0))


def make_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    d = df.copy()
    close = pd.to_numeric(d["close"], errors="coerce")
    high = pd.to_numeric(d["high"], errors="coerce")
    low = pd.to_numeric(d["low"], errors="coerce")
    open_ = pd.to_numeric(d["open"], errors="coerce")
    buy = pd.to_numeric(d["buy_notional"], errors="coerce").fillna(0.0)
    sell = pd.to_numeric(d["sell_notional"], errors="coerce").fillna(0.0)
    turnover = pd.to_numeric(d["turnover"], errors="coerce").fillna(buy + sell)
    volume = pd.to_numeric(d["volume"], errors="coerce").fillna(0.0)
    trades = pd.to_numeric(d["trade_count"], errors="coerce").fillna(0.0)
    mx = pd.to_numeric(d["max_trade_notional"], errors="coerce").fillna(0.0)
    d["f_body_1m"] = close / open_ - 1.0
    d["f_range_1m"] = high / low - 1.0
    d["f_close_pos_1m"] = (close - low) / (high - low).replace(0, np.nan)
    d["f_log_turnover_1m"] = log1p_nonneg(turnover)
    d["f_log_volume_1m"] = log1p_nonneg(volume)
    d["f_log_trades_1m"] = log1p_nonneg(trades)
    d["f_max_trade_share_1m"] = mx / turnover.replace(0, np.nan)
    d["f_flow_imbalance_1m"] = (buy - sell) / (buy + sell).replace(0, np.nan)
    d["f_gap"] = d.get("gap", False).astype(float)

    for w in FEATURE_WINDOWS:
        rb = buy.rolling(w, min_periods=w).sum()
        rs = sell.rolling(w, min_periods=w).sum()
        rt = turnover.rolling(w, min_periods=w).sum()
        rv = volume.rolling(w, min_periods=w).sum()
        rc = trades.rolling(w, min_periods=w).sum()
        rmx = mx.rolling(w, min_periods=w).max()
        ret = close.pct_change(w, fill_method=None)
        imb = (rb - rs) / (rb + rs).replace(0, np.nan)
        vol = close.pct_change(fill_method=None).rolling(w, min_periods=max(2, min(w, 5))).std()
        rh = high.rolling(w, min_periods=w).max()
        rl = low.rolling(w, min_periods=w).min()
        d[f"f_ret_{w}m"] = ret
        d[f"f_absret_{w}m"] = ret.abs()
        d[f"f_flow_{w}m"] = imb
        d[f"f_flow_price_agree_{w}m"] = ret * imb
        d[f"f_buy_response_{w}m"] = ret.clip(lower=0) * rb / (rb + rs).replace(0, np.nan)
        d[f"f_sell_response_{w}m"] = (-ret).clip(lower=0) * rs / (rb + rs).replace(0, np.nan)
        d[f"f_buy_eff_{w}m"] = ret.clip(lower=0) / (imb.abs() + 0.05)
        d[f"f_sell_eff_{w}m"] = (-ret).clip(lower=0) / (imb.abs() + 0.05)
        d[f"f_log_turnover_{w}m"] = log1p_nonneg(rt)
        d[f"f_log_volume_{w}m"] = log1p_nonneg(rv)
        d[f"f_log_trades_{w}m"] = log1p_nonneg(rc)
        d[f"f_max_trade_share_{w}m"] = rmx / rt.replace(0, np.nan)
        d[f"f_vol_{w}m"] = vol
        d[f"f_pos_{w}m"] = (close - rl) / (rh - rl).replace(0, np.nan)
        d[f"f_range_{w}m"] = rh / rl - 1.0
        d[f"f_dist_high_{w}m"] = rh / close - 1.0
        d[f"f_dist_low_{w}m"] = close / rl - 1.0

    d["f_ret_accel_1v5"] = d["f_ret_1m"] - d["f_ret_5m"] / 5.0
    d["f_ret_accel_3v15"] = d["f_ret_3m"] / 3.0 - d["f_ret_15m"] / 15.0
    d["f_flow_accel_5v30"] = d["f_flow_5m"] - d["f_flow_30m"]
    d["f_buy_eff_growth_5v30"] = d["f_buy_eff_5m"] - d["f_buy_eff_30m"]
    d["f_sell_eff_growth_5v30"] = d["f_sell_eff_5m"] - d["f_sell_eff_30m"]
    d["f_vol_ratio_5v60"] = d["f_vol_5m"] / d["f_vol_60m"].replace(0, np.nan)

    longs, shorts = [], []
    for h in TARGET_HORIZONS:
        fh = future_max(high, h)
        fl = future_min(low, h)
        up = fh / close - 1.0
        down = 1.0 - fl / close
        lv = up - 1.15 * down - COST
        sv = down - 1.15 * up - COST
        d[f"y_long_value_{h}m"] = lv
        d[f"y_short_value_{h}m"] = sv
        longs.append(lv)
        shorts.append(sv)
    d["y_long_value"] = pd.concat(longs, axis=1).max(axis=1)
    d["y_short_value"] = pd.concat(shorts, axis=1).max(axis=1)
    features = [c for c in d.columns if c.startswith("f_")]
    return d.replace([np.inf, -np.inf], np.nan), features


def build_dataset(root: Path):
    parts, features = [], None
    for period, rel in PERIODS:
        raw = load_jsonl_gz(root / rel)
        raw["period"] = period
        feat, cols = make_features(raw)
        parts.append(feat)
        features = cols if features is None else features
    return pd.concat(parts, ignore_index=True), features


def new_model():
    return make_pipeline(
        SimpleImputer(strategy="median", add_indicator=True),
        ExtraTreesRegressor(n_estimators=160, max_depth=12, min_samples_leaf=18,
                            max_features=0.72, n_jobs=-1, random_state=42),
    )


def fit_models(train: pd.DataFrame, features: list[str]):
    ok = train["y_long_value"].notna() & train["y_short_value"].notna() & (train["f_gap"] == 0)
    ml, ms = new_model(), new_model()
    ml.fit(train.loc[ok, features], train.loc[ok, "y_long_value"])
    ms.fit(train.loc[ok, features], train.loc[ok, "y_short_value"])
    return ml, ms


def predict(df: pd.DataFrame, features: list[str], ml, ms):
    out = df.copy()
    out["pred_long"] = ml.predict(out[features])
    out["pred_short"] = ms.predict(out[features])
    out["pred_edge"] = out["pred_long"] - out["pred_short"]
    return out


def simulate(df: pd.DataFrame, p: dict[str, float], collect=False):
    side, entry, entry_ts = 0, 0.0, 0
    mfe, mae = 0.0, 0.0
    trades = []
    equity, peak, maxdd = 1.0, 1.0, 0.0
    last_exit_i = -10**9

    for i, r in df.iterrows():
        if bool(r.get("gap", False)) or not np.isfinite(r["close"]):
            continue
        price, high, low = float(r["close"]), float(r["high"]), float(r["low"])
        lv, sv = float(r["pred_long"]), float(r["pred_short"])
        best, edge = max(lv, sv), abs(lv - sv)
        if side == 0:
            if i - last_exit_i >= int(p["cooldown_min"]) and best >= p["entry"] and edge >= p["edge"]:
                side = 1 if lv > sv else -1
                entry, entry_ts, mfe, mae = price, int(r["ts_ms"]), 0.0, 0.0
            continue

        if side > 0:
            fav, adv, cur, own, opp = high / entry - 1.0, low / entry - 1.0, price / entry - 1.0, lv, sv
        else:
            fav, adv, cur, own, opp = 1.0 - low / entry, 1.0 - high / entry, 1.0 - price / entry, sv, lv
        mfe, mae = max(mfe, fav), min(mae, adv)
        recoil = max(0.0, mfe - cur)

        reason, reverse = None, False
        if opp >= p["entry"] and opp - own >= p["reverse_edge"]:
            reason, reverse = "REVERSE", True
        elif mfe >= p["mfe_arm"] and recoil >= max(p["giveback_floor"], p["giveback_frac"] * mfe) and own < p["hold"]:
            reason = "MFE_WEAKEN"
        elif own < p["hard_exit"] and cur < 0:
            reason = "NEGATIVE_CONTINUATION"

        if reason:
            net = cur - COST
            equity *= max(1e-9, 1.0 + net)
            peak, maxdd = max(peak, equity), max(maxdd, 1.0 - equity / max(peak, 1e-12))
            trades.append({
                "period": r["period"], "side": "LONG" if side > 0 else "SHORT",
                "entry_ts_ms": entry_ts, "exit_ts_ms": int(r["ts_ms"]),
                "entry_price": entry, "exit_price": price,
                "gross_return": cur, "net_return": net, "mfe": mfe, "mae": mae,
                "mfe_capture_ratio": cur / mfe if mfe > 1e-9 else None,
                "mfe_giveback": max(0.0, mfe - cur),
                "hold_min": (int(r["ts_ms"]) - entry_ts) / 60000.0, "reason": reason,
            })
            old = side
            side, last_exit_i = 0, i
            if reverse:
                side, entry, entry_ts, mfe, mae = -old, price, int(r["ts_ms"]), 0.0, 0.0

    if side != 0 and len(df):
        r = df.iloc[-1]
        price = float(r["close"])
        cur = price / entry - 1.0 if side > 0 else 1.0 - price / entry
        net = cur - COST
        equity *= max(1e-9, 1.0 + net)
        trades.append({
            "period": r["period"], "side": "LONG" if side > 0 else "SHORT",
            "entry_ts_ms": entry_ts, "exit_ts_ms": int(r["ts_ms"]),
            "entry_price": entry, "exit_price": price, "gross_return": cur, "net_return": net,
            "mfe": mfe, "mae": mae, "mfe_capture_ratio": cur / mfe if mfe > 1e-9 else None,
            "mfe_giveback": max(0.0, mfe - cur),
            "hold_min": (int(r["ts_ms"]) - entry_ts) / 60000.0, "reason": "PERIOD_END",
        })

    t = pd.DataFrame(trades)
    if t.empty:
        return {"trades":0,"net_compound":0.0,"max_drawdown":0.0,"win_rate":0.0,"profit_factor":0.0}, t
    gains = t.loc[t.net_return > 0, "net_return"].sum()
    losses = -t.loc[t.net_return < 0, "net_return"].sum()
    caps = t["mfe_capture_ratio"].replace([np.inf, -np.inf], np.nan).dropna()
    m = {
        "trades": int(len(t)), "net_compound": float(np.prod(1.0 + t.net_return) - 1.0),
        "net_sum": float(t.net_return.sum()), "max_drawdown": float(maxdd),
        "win_rate": float((t.net_return > 0).mean()),
        "profit_factor": float(gains / losses) if losses > 0 else 99.0,
        "median_trade": float(t.net_return.median()), "mean_trade": float(t.net_return.mean()),
        "median_mfe": float(t.mfe.median()), "median_mae": float(t.mae.median()),
        "median_mfe_capture": float(caps.median()) if len(caps) else None,
        "median_mfe_giveback": float(t.mfe_giveback.median()),
        "p90_mfe_giveback": float(t.mfe_giveback.quantile(.9)),
        "median_hold_min": float(t.hold_min.median()),
        "long_trades": int((t.side=="LONG").sum()), "short_trades": int((t.side=="SHORT").sum()),
    }
    return m, t if collect else pd.DataFrame()


def tune(val: pd.DataFrame):
    score = np.maximum(val.pred_long.to_numpy(), val.pred_short.to_numpy())
    edgev = np.abs(val.pred_edge.to_numpy())
    entries = sorted(set(float(np.quantile(score[np.isfinite(score)], q)) for q in (.45,.55,.65,.75,.85)))
    edges = sorted(set(float(np.quantile(edgev[np.isfinite(edgev)], q)) for q in (.20,.40,.60)))
    rows, best, best_obj = [], None, -1e99
    for entry in entries:
        for edge in edges:
            for hr in (0.0,.25,.50):
                for arm in (.002,.004,.006):
                    for frac in (.30,.45,.60):
                        p={"entry":entry,"edge":edge,"hold":entry*hr,"hard_exit":-COST*.5,
                           "mfe_arm":arm,"giveback_floor":.0015,"giveback_frac":frac,
                           "reverse_edge":max(edge,COST*.5),"cooldown_min":1}
                        m,_=simulate(val,p)
                        obj=m["net_compound"]-1.5*m["max_drawdown"]-.00035*m["trades"]
                        rows.append({**p,**m,"objective":obj})
                        if m["trades"]>=8 and obj>best_obj:
                            best_obj,best=obj,p
    rows.sort(key=lambda z:z["objective"],reverse=True)
    return best,rows[:50]


def leverage_stress(t: pd.DataFrame, lev: int, margin=.20):
    eq=peak=1.0; maxdd=0.0; liqs=0; exposure=lev*margin; barrier=-.90/lev
    for _,r in t.iterrows():
        if float(r.mae)<=barrier:
            eq*=1-margin; liqs+=1
        else:
            eq*=max(1e-9,1+exposure*float(r.net_return))
        peak=max(peak,eq); maxdd=max(maxdd,1-eq/peak)
    return {"leverage":lev,"margin_fraction":margin,"exposure_multiple":exposure,
            "ending_equity_multiple":float(eq),"return_pct":float((eq-1)*100),
            "max_drawdown":float(maxdd),"approx_liquidations":liqs,
            "approx_liquidation_barrier_underlying":float(barrier)}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,required=True); ap.add_argument("--out",type=Path,required=True)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=True)
    data,features=build_dataset(a.root)
    assert all(x.startswith("f_") for x in features)
    p1=data[data.period=="P1_JUL12_AUG07"].copy(); p2=data[data.period=="P2_AUG08_SEP01"].copy()
    p3=data[data.period=="P3_SEP01_OCT01"].copy(); p4=data[data.period=="P4_OCT04_NOV03"].copy()

    ml,ms=fit_models(p1,features); p2p=predict(p2,features,ml,ms)
    policy,top=tune(p2p); vm,vt=simulate(p2p,policy,True)

    ml,ms=fit_models(pd.concat([p1,p2],ignore_index=True),features); p3p=predict(p3,features,ml,ms)
    tm,tt=simulate(p3p,policy,True)

    ml,ms=fit_models(pd.concat([p1,p2,p3],ignore_index=True),features); p4p=predict(p4,features,ml,ms)
    hm,ht=simulate(p4p,policy,True)

    oos=pd.concat([tt,ht],ignore_index=True)
    gains=oos.loc[oos.net_return>0,"net_return"].sum() if len(oos) else 0
    losses=-oos.loc[oos.net_return<0,"net_return"].sum() if len(oos) else 0
    comb={"trades":int(len(oos)),"net_compound":float(np.prod(1+oos.net_return)-1) if len(oos) else 0,
          "win_rate":float((oos.net_return>0).mean()) if len(oos) else 0,
          "profit_factor":float(gains/losses) if losses>0 else 99.0,
          "median_mfe_capture":float(oos.mfe_capture_ratio.replace([np.inf,-np.inf],np.nan).dropna().median()) if len(oos) else None,
          "median_mfe_giveback":float(oos.mfe_giveback.median()) if len(oos) else None,
          "median_mae":float(oos.mae.median()) if len(oos) else None}
    lev=[leverage_stress(oos,x) for x in (1,2,3,5,8,10,15,20,25)]
    report={"version":"HYPE-MOVEMENT-SIGNATURE-REPLAY-v1","research_only":True,"real_orders":False,
            "cost_round_trip":COST,"feature_count":len(features),
            "feature_contract":"common causal movement features from compact 1m Bybit price/trade tape; no Local/teacher predictors",
            "validation_design":{"P1":"Jul12-Aug07 model development","P2":"Aug08-Sep01 policy threshold selection",
            "P3":"Sep01-Oct01 frozen-policy test, model uses prior P1+P2","P4":"Oct04-Nov03 frozen-policy holdout, model uses prior P1+P2+P3"},
            "policy":policy,"validation":vm,"test":tm,"final_holdout":hm,"combined_strict_oos_P3_P4":comb,
            "leverage_stress_P3_P4":lev,"top_validation_candidates":top[:15],
            "warnings":["P2 selects thresholds and is not OOS.","P3/P4 thresholds are frozen.",
            "Leverage stress is approximate, not exact Bybit maintenance-margin math.",
            "Missing historical L50/OI/liquidations are not fabricated.","Full-116 live shadow remains required."]}
    (a.out/"MOVEMENT_SIGNATURE_REPLAY_V1.json").write_text(json.dumps(report,indent=2)+"\n")
    pd.concat([vt.assign(scope="P2_VALIDATION"),tt.assign(scope="P3_TEST"),ht.assign(scope="P4_HOLDOUT")]).to_csv(a.out/"MOVEMENT_SIGNATURE_TRADES_V1.csv",index=False)
    pd.DataFrame(top).to_csv(a.out/"MOVEMENT_SIGNATURE_POLICY_SEARCH_TOP50.csv",index=False)
    lines=["# HYPE Movement Signature Replay V1","", "Research only. No real orders.",
           f"- causal features: {len(features)}",f"- round-trip cost: {COST*10000:.1f} bps",
           f"- frozen policy after P2: {json.dumps(policy,sort_keys=True)}","",
           "## Walk-forward",f"- P2 validation: {json.dumps(vm,sort_keys=True)}",
           f"- P3 test: {json.dumps(tm,sort_keys=True)}",f"- P4 holdout: {json.dumps(hm,sort_keys=True)}",
           f"- combined P3+P4: {json.dumps(comb,sort_keys=True)}","","## Leverage stress P3+P4"]
    for x in lev:
        lines.append(f"- {x['leverage']}x, 20% margin: end {x['ending_equity_multiple']:.4f}x, return {x['return_pct']:.2f}%, maxDD {x['max_drawdown']:.2%}, approx_liq {x['approx_liquidations']}")
    lines += ["","This engine trades movement value, not Local labels.","Freeze and score full-116 live shadow before any real-order use."]
    (a.out/"MOVEMENT_SIGNATURE_REPLAY_V1.md").write_text("\n".join(lines)+"\n")
    print(json.dumps(report,sort_keys=True))


if __name__=="__main__":
    main()
