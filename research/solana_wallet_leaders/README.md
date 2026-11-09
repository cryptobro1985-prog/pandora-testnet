# Solana Wallet Leaders — research-only prototype

Goal: identify on-chain wallet A that repeatedly buys a Solana token before B/C/D, with observed positive time separation. This is NOT a trading strategy or proven profitable copytrading system.

Run: `python research/solana_wallet_leaders/collector.py`. Optional GitHub secret `SOLANA_RPC_URL` for a higher-capacity RPC; otherwise the public mainnet endpoint is used. Output: `latest_report.json` and rolling `state.json`.

GitHub Actions cron is best-effort and **not continuous**. GitHub may delay or skip scheduled runs. Workflows stored on a non-default branch generally cannot be scheduled by GitHub until the workflow is on the default branch. This branch is intentionally isolated; workflow activation on main requires explicit review. `workflow_dispatch` may also require the workflow on the default branch.

Limitations: DexScreener latest profiles/boosts are a non-exhaustive discovery source; mint signatures do not reliably enumerate all swap transactions; token balance deltas and signer matching can miss delegated trading; repeated sequences do not establish wallet common ownership; no slippage, sell exit, liquidity, profit, funding network, or out-of-sample validation. All candidates must remain unverified until independently audited. Do not connect private keys or execute trades.

Next: reliable Pump.fun trade indexing (e.g. paid indexed provider), transaction decoding, funding graph, bundle detection, pricing and forward PAPER execution simulation. For actual uninterrupted collection deploy a persistent worker with database and RPC/WebSocket provider.
