# Current handoff

Branch: `caterpillar-paper-runtime-v1`, based on main `47023e5`.

Implemented: isolated public-data runtime, session-frozen dynamic top five/manual override, causal research H1, execution-block Flow, explicit entry/hold/transfer/exit/correction/re-entry states, next-trade fills, shared $500/20%/25x portfolio, fees/slippage, contract size limits, MFE/MAE, conservative maintenance, atomic SQLite/checkpoint restore, complete journal artifact, GitHub-native static monitor, gated Actions workflow and finite continuation by a subsequent branch push/dispatch.

Validation completed locally: 31 PAPER tests, 112 existing research tests; mobile Chromium 360px. Root legacy application's unrelated baseline failures remain documented in EVIDENCE.md. Live probe created session `db54e78e-31e1-4a4d-94be-a68dbf423123`, equity $500, no positions and no selected tokens because Bybit requests were denied. This was an access-failure probe, not a live successful session.

Network: native Git access works with `git -c credential.helper='!gh auth git-credential' ...`; credentials are consumed by Git and never printed. `api.github.com`, `docs.github.com`, `api.bybit.com`, `stream.bybit.com` and the owner's Pages hostname were added to the environment draft but the running proxy still denied requests. Review/apply the saved network settings before retrying. Do not request API keys for public market data.

Next concrete operations after remote push: inspect **Caterpillar PAPER Runtime**, confirm critical gates and research artifact retrieval; inspect run logs and monitor-data branch; verify Pages source creation without replacing any existing site; fetch the actual Pages URL and state.json; confirm current session, recent update, five current instruments, closed H1s and actual fresh publicTrade messages. If API access remains blocked locally, use working native Git to fetch the monitor-data branch and read its snapshot, but do not call the public URL verified from Git data alone.

Workflow dispatch on a new branch may require the workflow to be discoverable on the default branch. A push to this isolated branch is the supported first trigger; do not modify main merely to enable dispatch. No automatic recursion is configured. Later runs restore the latest same-branch artifact, retaining the same session and losses. Manual symbol/config changes against a different checkpoint are rejected; choose a deliberately new output/session for changed parameters.

Research limits: original successful PnL/account identity and cross-token result artifacts remain unverified locally. The workflow retrieves the existing five small synthesis evidence artifacts where available; it does not re-run a large backtest or auto-tune trading rules. The correction-depth rule is an explicit cost-scaled hypothesis. A new PAPER candidate is not a verified reconstruction of the profitable historical engine. Never force trades or report a synthetic test position as real PAPER activity.
