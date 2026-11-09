#!/usr/bin/env python3
"""Pump.fun early-wallet / insider-candidate research.

Research only. No private keys, no order submission, no copy-trading.
Inspired by the transaction-first wallet discovery pattern used by Kaiser.charon,
but independently implemented around observable Solana balance deltas.

Outputs:
  state.json              rolling decoded observations
  latest_report.json      ranked wallet evidence
  dorado_candidates.yaml  candidate-only wallet list; never live-approved
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import math
import os
import pathlib
import statistics
import time
import urllib.parse
import urllib.request
from typing import Any

ROOT = pathlib.Path("research/solana_wallet_leaders")
ROOT.mkdir(parents=True, exist_ok=True)
STATE = ROOT / "state.json"
REPORT = ROOT / "latest_report.json"
DORADO = ROOT / "dorado_candidates.yaml"

RPC = (os.getenv("SOLANA_RPC_URL") or "").strip() or "https://api.mainnet-beta.solana.com"
UA = {"User-Agent": "pandora-pumpfun-insider-research/2.0"}
MAX_TOKENS = max(8, int(os.getenv("MAX_TOKENS", "48")))
SIGS_PER_TOKEN = max(20, min(250, int(os.getenv("SIGNATURES_PER_TOKEN", "90"))))
MAX_TX_PER_RUN = max(200, int(os.getenv("MAX_TX_PER_RUN", "3200")))
RPC_SLEEP = max(0.01, float(os.getenv("RPC_SLEEP_SECONDS", "0.045")))
EARLY_RANK = max(3, int(os.getenv("EARLY_RANK", "12")))
LEADER_WINDOW_S = max(30, int(os.getenv("LEADER_WINDOW_SECONDS", "600")))
MIN_REPEAT_TOKENS = max(2, int(os.getenv("MIN_REPEAT_TOKENS", "3")))
MAX_EVENTS = max(5000, int(os.getenv("MAX_EVENTS", "60000")))


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_json(path: pathlib.Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return default


def write_json(path: pathlib.Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=22) as r:
        return json.load(r)


def rpc(method: str, params: list[Any]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json", **UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("error"):
        raise RuntimeError(f"{method}: {data['error']}")
    return data.get("result")


def looks_like_mint(value: Any) -> bool:
    return isinstance(value, str) and 32 <= len(value) <= 50 and value not in {
        "So11111111111111111111111111111111111111112",
        "11111111111111111111111111111111",
    }


def discover_mints() -> list[str]:
    """Best-effort public discovery. No claim of exhaustive Pump.fun coverage."""
    found: list[tuple[str, str]] = []

    endpoints = [
        ("profile", "https://api.dexscreener.com/token-profiles/latest/v1"),
        ("boost_latest", "https://api.dexscreener.com/token-boosts/latest/v1"),
        ("boost_top", "https://api.dexscreener.com/token-boosts/top/v1"),
    ]
    for source, url in endpoints:
        try:
            rows = http_json(url)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if row.get("chainId") != "solana":
                    continue
                mint = row.get("tokenAddress")
                if looks_like_mint(mint):
                    found.append((mint, source))
        except Exception as exc:
            print("discovery_error", source, str(exc)[:180], flush=True)

    for query in ("pump.fun", "pumpfun", "pump"):
        try:
            url = "https://api.dexscreener.com/latest/dex/search/?" + urllib.parse.urlencode({"q": query})
            data = http_json(url)
            for pair in (data or {}).get("pairs") or []:
                if pair.get("chainId") != "solana":
                    continue
                for side in ("baseToken", "quoteToken"):
                    mint = (pair.get(side) or {}).get("address")
                    if looks_like_mint(mint) and (str(mint).endswith("pump") or side == "baseToken"):
                        found.append((mint, "search:" + query))
        except Exception as exc:
            print("search_discovery_error", query, str(exc)[:180], flush=True)

    # Pump.fun mints commonly end in 'pump'; prioritize those, then all Solana discoveries.
    seen = set()
    prioritized = sorted(found, key=lambda z: (not z[0].endswith("pump"), z[1], z[0]))
    out = []
    for mint, _source in prioritized:
        if mint in seen:
            continue
        seen.add(mint)
        out.append(mint)
        if len(out) >= MAX_TOKENS:
            break
    return out


def signatures_for_address(address: str, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    before = None
    while len(rows) < limit:
        page_limit = min(100, limit - len(rows))
        cfg: dict[str, Any] = {"limit": page_limit}
        if before:
            cfg["before"] = before
        page = rpc("getSignaturesForAddress", [address, cfg]) or []
        if not page:
            break
        rows.extend(page)
        before = page[-1].get("signature")
        if len(page) < page_limit:
            break
        time.sleep(RPC_SLEEP)
    return rows


def key_rows(message: dict[str, Any]) -> tuple[list[str], set[str]]:
    keys: list[str] = []
    signers: set[str] = set()
    for item in message.get("accountKeys") or []:
        if isinstance(item, dict):
            pub = item.get("pubkey")
            if pub:
                keys.append(str(pub))
                if item.get("signer"):
                    signers.add(str(pub))
        elif isinstance(item, str):
            keys.append(item)
    return keys, signers


def token_owner_balances(meta: dict[str, Any], mint: str) -> tuple[dict[str, int], dict[str, int]]:
    pre: dict[str, int] = collections.defaultdict(int)
    post: dict[str, int] = collections.defaultdict(int)
    for row in meta.get("preTokenBalances") or []:
        if row.get("mint") == mint and row.get("owner"):
            try:
                pre[str(row["owner"])] += int((row.get("uiTokenAmount") or {}).get("amount") or 0)
            except Exception:
                pass
    for row in meta.get("postTokenBalances") or []:
        if row.get("mint") == mint and row.get("owner"):
            try:
                post[str(row["owner"])] += int((row.get("uiTokenAmount") or {}).get("amount") or 0)
            except Exception:
                pass
    return dict(pre), dict(post)


def decode_wallet_events(mint: str, sig_row: dict[str, Any], tx: dict[str, Any]) -> list[dict[str, Any]]:
    meta = (tx or {}).get("meta") or {}
    if not meta or meta.get("err"):
        return []
    message = ((tx or {}).get("transaction") or {}).get("message") or {}
    keys, signers = key_rows(message)
    pre_lam = meta.get("preBalances") or []
    post_lam = meta.get("postBalances") or []
    pre_tok, post_tok = token_owner_balances(meta, mint)
    block_time = sig_row.get("blockTime") or tx.get("blockTime")
    if not block_time:
        return []

    key_index = {k: i for i, k in enumerate(keys)}
    out = []
    for owner in set(pre_tok) | set(post_tok):
        delta = int(post_tok.get(owner, 0)) - int(pre_tok.get(owner, 0))
        if delta == 0:
            continue
        # Restrict to a wallet account present in the transaction. Prefer signer-owned changes.
        idx = key_index.get(owner)
        if idx is None:
            continue
        if signers and owner not in signers:
            continue
        sol_delta = 0.0
        if idx < len(pre_lam) and idx < len(post_lam):
            sol_delta = (float(post_lam[idx]) - float(pre_lam[idx])) / 1e9
        side = "BUY" if delta > 0 else "SELL"
        out.append({
            "mint": mint,
            "wallet": owner,
            "side": side,
            "signature": sig_row.get("signature"),
            "slot": int(sig_row.get("slot") or 0),
            "block_time": int(block_time),
            "token_delta_raw": str(delta),
            "sol_delta": sol_delta,
            "sol_in": max(0.0, -sol_delta) if side == "BUY" else 0.0,
            "sol_out": max(0.0, sol_delta) if side == "SELL" else 0.0,
            "fee_sol": float(meta.get("fee") or 0) / 1e9,
        })
    return out


def dedupe_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    out = []
    for row in rows:
        key = (row.get("signature"), row.get("wallet"), row.get("mint"), row.get("side"), row.get("token_delta_raw"))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    out.sort(key=lambda r: (int(r.get("block_time") or 0), int(r.get("slot") or 0), str(r.get("signature") or "")))
    return out[-MAX_EVENTS:]


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def build_rankings(events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_mint: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for e in events:
        by_mint[str(e["mint"])].append(e)

    wallet_tokens: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
    leader_followers: dict[str, set[str]] = collections.defaultdict(set)
    leader_sequences: collections.Counter[str] = collections.Counter()

    token_summaries: dict[str, Any] = {}
    for mint, rows in by_mint.items():
        rows.sort(key=lambda r: (r["block_time"], r.get("slot") or 0))
        buys = [r for r in rows if r["side"] == "BUY"]
        first_buy_by_wallet: dict[str, dict[str, Any]] = {}
        for r in buys:
            first_buy_by_wallet.setdefault(r["wallet"], r)
        ordered_buyers = sorted(first_buy_by_wallet.values(), key=lambda r: (r["block_time"], r.get("slot") or 0))
        first_ts = ordered_buyers[0]["block_time"] if ordered_buyers else None
        rank_map = {r["wallet"]: i + 1 for i, r in enumerate(ordered_buyers)}

        for wallet in {r["wallet"] for r in rows}:
            wr = [r for r in rows if r["wallet"] == wallet]
            wb = [r for r in wr if r["side"] == "BUY"]
            ws = [r for r in wr if r["side"] == "SELL"]
            if not wb:
                continue
            bought_raw = sum(max(0, int(r["token_delta_raw"])) for r in wb)
            sold_raw = sum(max(0, -int(r["token_delta_raw"])) for r in ws)
            sol_in = sum(float(r.get("sol_in") or 0.0) for r in wb)
            sol_out = sum(float(r.get("sol_out") or 0.0) for r in ws)
            entry = min(wb, key=lambda r: (r["block_time"], r.get("slot") or 0))
            exit_row = max(ws, key=lambda r: (r["block_time"], r.get("slot") or 0)) if ws else None
            completion = min(1.0, sold_raw / max(1, bought_raw))
            complete = completion >= 0.80 and bool(ws)
            wallet_tokens[wallet][mint] = {
                "entry_rank": rank_map.get(wallet),
                "entry_delay_from_first_observed_buy_s": (entry["block_time"] - first_ts) if first_ts else None,
                "entry_time": entry["block_time"],
                "exit_time": exit_row["block_time"] if exit_row else None,
                "buy_sol_observed": sol_in,
                "sell_sol_observed": sol_out,
                "net_sol_observed": sol_out - sol_in,
                "token_completion_ratio": completion,
                "roundtrip_complete": complete,
                "roundtrip_win": bool(complete and sol_out > sol_in),
                "buy_events": len(wb),
                "sell_events": len(ws),
            }

        # Relative leadership evidence inside each token.
        for i, a in enumerate(ordered_buyers):
            for b in ordered_buyers[i + 1:]:
                delay = int(b["block_time"]) - int(a["block_time"])
                if delay <= 0:
                    continue
                if delay > LEADER_WINDOW_S:
                    break
                leader_sequences[a["wallet"]] += 1
                leader_followers[a["wallet"]].add(b["wallet"])

        token_summaries[mint] = {
            "observed_events": len(rows),
            "observed_buyers": len(ordered_buyers),
            "first_observed_buy_time": first_ts,
        }

    rankings = []
    for wallet, token_map in wallet_tokens.items():
        samples = list(token_map.values())
        distinct = len(samples)
        ranks = [int(x["entry_rank"]) for x in samples if x.get("entry_rank")]
        delays = [float(x["entry_delay_from_first_observed_buy_s"]) for x in samples if x.get("entry_delay_from_first_observed_buy_s") is not None]
        early = sum(1 for x in samples if (x.get("entry_rank") or 10**9) <= EARLY_RANK)
        completed = [x for x in samples if x["roundtrip_complete"]]
        wins = sum(1 for x in completed if x["roundtrip_win"])
        total_in = sum(float(x["buy_sol_observed"]) for x in samples)
        total_out = sum(float(x["sell_sol_observed"]) for x in samples)
        observed_net = total_out - total_in
        early_share = early / distinct if distinct else 0.0
        win_rate = wins / len(completed) if completed else None
        med_rank = median([float(x) for x in ranks])
        med_delay = median(delays)
        followers = len(leader_followers.get(wallet, set()))
        leader_count = int(leader_sequences.get(wallet, 0))

        repeat_score = min(30.0, distinct * 5.0)
        early_score = 25.0 * early_share
        rank_score = 0.0 if med_rank is None else 15.0 * max(0.0, 1.0 - (med_rank - 1.0) / max(EARLY_RANK * 2.0, 1.0))
        win_score = 0.0 if win_rate is None else 15.0 * win_rate * min(1.0, len(completed) / 4.0)
        pnl_score = 10.0 * (0.5 + 0.5 * math.tanh(observed_net / max(0.25, total_in * 0.35))) if total_in > 0 else 0.0
        leader_score = min(5.0, 0.25 * leader_count + 0.15 * followers)
        score = max(0.0, min(100.0, repeat_score + early_score + rank_score + win_score + pnl_score + leader_score))

        if distinct >= 7 and len(completed) >= 3:
            confidence = "HIGH"
        elif distinct >= 4 and len(completed) >= 1:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        if distinct >= MIN_REPEAT_TOKENS and early_share >= 0.70 and (med_rank or 999) <= 6:
            profile = "INSIDER_CANDIDATE"
        elif distinct >= MIN_REPEAT_TOKENS and (med_rank or 999) <= EARLY_RANK:
            profile = "REPEAT_SNIPER"
        elif distinct >= 5 and win_rate is not None and win_rate >= 0.55:
            profile = "RUNNER_SELECTOR"
        else:
            profile = "OBSERVED_WALLET"

        rankings.append({
            "wallet": wallet,
            "score": round(score, 3),
            "profile": profile,
            "confidence": confidence,
            "distinct_tokens": distinct,
            "early_entries": early,
            "early_share": round(early_share, 4),
            "median_entry_rank": med_rank,
            "median_delay_from_first_observed_buy_s": med_delay,
            "completed_roundtrips": len(completed),
            "roundtrip_wins": wins,
            "observed_roundtrip_win_rate": round(win_rate, 4) if win_rate is not None else None,
            "observed_buy_sol": round(total_in, 9),
            "observed_sell_sol": round(total_out, 9),
            "observed_net_sol": round(observed_net, 9),
            "leader_sequences": leader_count,
            "unique_followers_within_window": followers,
            "tokens": dict(sorted(token_map.items(), key=lambda kv: kv[1]["entry_time"])[:40]),
            "live_copytrade_approved": False,
        })

    rankings.sort(key=lambda r: (-r["score"], -r["distinct_tokens"], r["median_entry_rank"] or 999999))
    diagnostics = {
        "mints_with_events": len(by_mint),
        "wallets_observed": len(wallet_tokens),
        "token_summaries": token_summaries,
    }
    return rankings, diagnostics


def write_dorado_candidates(rankings: list[dict[str, Any]]) -> None:
    candidates = [
        r for r in rankings
        if r["distinct_tokens"] >= MIN_REPEAT_TOKENS
        and r["profile"] in {"INSIDER_CANDIDATE", "REPEAT_SNIPER", "RUNNER_SELECTOR"}
    ][:100]
    lines = [
        "# Auto-generated research candidates for DoradoDevs/solana-pumpfun-sniper-bot",
        "# RESEARCH ONLY: every candidate remains live_copytrade_approved=false.",
        "# Do not place these into a funded live bot without independent validation.",
        "kol_wallets: []",
        "wallets:",
    ]
    if not candidates:
        lines.append("  []")
    for i, r in enumerate(candidates, 1):
        trust = max(0.50, min(0.99, r["score"] / 100.0))
        priority = 1 if r["score"] >= 80 else 2 if r["score"] >= 65 else 3
        lines.extend([
            f"  - address: {r['wallet']}",
            f"    name: research-{r['profile'].lower().replace('_','-')}-{i:03d}",
            "    type: smart_money",
            f"    priority: {priority}",
            f"    trust: {trust:.2f}",
            "    live_copytrade_approved: false",
            f"    evidence_tokens: {r['distinct_tokens']}",
            f"    observed_score: {r['score']:.3f}",
        ])
    DORADO.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    state = load_json(STATE, {"version": 2, "mints": {}, "events": []})
    if int(state.get("version") or 0) != 2:
        state = {"version": 2, "mints": {}, "events": []}

    mints = discover_mints()
    errors: list[str] = []
    tx_seen = 0
    new_events: list[dict[str, Any]] = []

    print(json.dumps({"phase": "discover", "mints": len(mints), "generated_at": utcnow()}), flush=True)

    for mint_i, mint in enumerate(mints, 1):
        if tx_seen >= MAX_TX_PER_RUN:
            break
        known = set(state.get("mints", {}).get(mint, []))
        try:
            sigs = signatures_for_address(mint, SIGS_PER_TOKEN)
            # Oldest first so entry order is stable.
            for sig in reversed(sigs):
                if tx_seen >= MAX_TX_PER_RUN:
                    break
                signature = sig.get("signature")
                if not signature or signature in known or sig.get("err") is not None:
                    continue
                try:
                    tx = rpc("getTransaction", [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
                    tx_seen += 1
                    if tx:
                        new_events.extend(decode_wallet_events(mint, sig, tx))
                except Exception as exc:
                    errors.append(f"tx {signature}: {str(exc)[:180]}")
                time.sleep(RPC_SLEEP)
            state.setdefault("mints", {})[mint] = [s.get("signature") for s in sigs if s.get("signature")][:500]
        except Exception as exc:
            errors.append(f"mint {mint}: {str(exc)[:180]}")
        if mint_i % 5 == 0:
            print(json.dumps({"phase": "scan", "mints_done": mint_i, "tx_seen": tx_seen, "new_events": len(new_events), "errors": len(errors)}), flush=True)
        time.sleep(RPC_SLEEP)

    if mints and tx_seen == 0:
        raise RuntimeError(
            "RPC/data-path failure: discovered Pump.fun mints but decoded zero transactions; "
            f"rpc={RPC!r} errors={len(errors)} first_error={(errors[0] if errors else 'none')}"
        )

    events = dedupe_events(list(state.get("events") or []) + new_events)
    state["events"] = events
    state["updated_at"] = utcnow()
    rankings, diagnostics = build_rankings(events)

    report = {
        "generated_at": utcnow(),
        "research_only": True,
        "live_copytrade_approved": False,
        "method": "transaction-first Pump.fun early-wallet ranking; independently implemented from observable Solana token/native balance deltas",
        "discovery": {
            "mints_requested": MAX_TOKENS,
            "mints_discovered_this_run": len(mints),
            "signatures_per_mint": SIGS_PER_TOKEN,
            "max_transactions_per_run": MAX_TX_PER_RUN,
            "source_note": "DexScreener public discovery is non-exhaustive; ranking is evidence over observed sample, not proof of insider identity",
        },
        "run": {
            "transactions_decoded": tx_seen,
            "new_events": len(new_events),
            "total_events": len(events),
            "errors": errors[:80],
        },
        "diagnostics": diagnostics,
        "top_wallets": rankings[:150],
        "top_insider_candidates": [r for r in rankings if r["profile"] == "INSIDER_CANDIDATE"][:50],
        "top_repeat_snipers": [r for r in rankings if r["profile"] == "REPEAT_SNIPER"][:50],
        "top_runner_selectors": [r for r in rankings if r["profile"] == "RUNNER_SELECTOR"][:50],
        "limitations": [
            "Observed first buyer is first in the sampled transaction set, not guaranteed first on-chain buyer.",
            "Mint-address signature enumeration can miss program-routed swaps; an indexed Pump.fun source should be added for exhaustive coverage.",
            "SOL balance delta can include fees/rent/other instructions; it is evidence, not exchange-grade accounting.",
            "Open/partial positions are excluded from round-trip win rate until >=80% of observed token buys are sold.",
            "Repeated early entry does not prove common ownership, privileged information, or future profitability.",
            "No private keys are used and no orders are submitted.",
        ],
    }

    write_json(STATE, state)
    write_json(REPORT, report)
    write_dorado_candidates(rankings)
    print("INSIDER_RESEARCH_RESULT=" + json.dumps({
        "mints": len(mints),
        "tx_decoded": tx_seen,
        "new_events": len(new_events),
        "total_events": len(events),
        "wallets": diagnostics["wallets_observed"],
        "insider_candidates": len(report["top_insider_candidates"]),
        "repeat_snipers": len(report["top_repeat_snipers"]),
        "runner_selectors": len(report["top_runner_selectors"]),
        "errors": len(errors),
    }, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
