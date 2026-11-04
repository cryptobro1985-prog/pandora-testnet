# HYPE data acquisition evidence

Observed in this cloud task on 2026-11-04 UTC. Exact requests and timestamps are
stored in `acquisition.json`. No market dataset was downloaded. No replacement or
synthetic market data was substituted.

## Actual routes checked

- Native Git read access works for the requested repository and research branch.
- The `research/pandora-universal-30d-v1` ref
  (`b9c6d67bcb95ac84b57bf0efe579b039369acec4`) contains research code and workflow,
  but no HYPE minute/raw archive committed to Git.
- The `caterpillar-monitor-data` ref
  (`ad5696311e49979ad4e0cfbcb2a5b785067d6903`) contains `.nojekyll`, `index.html`,
  `state.json`; it is a runtime status snapshot, not the HYPE 30-day dataset.
- The tracked `PANDORA_WIN_COMPLETE.zip` source bundle has no HYPE trade/minute
  dataset.
- GitHub web artifact route
  `https://github.com/cryptobro1985-prog/pandora-testnet/actions/runs/41736806286/artifacts/13278474318`
  returned HTTP 404. This does not establish that the artifact is missing: private
  artifact web authentication differs from the Git read proxy.
- The GitHub Actions API artifact request fails at HTTPS CONNECT with 403.
- The official Bybit executed-trade archive request fails at HTTPS CONNECT with 403.
- The public historical OI REST request fails at HTTPS CONNECT with 403.

The last three results occur before reaching the origin server. They therefore
establish a current cloud egress restriction, not an expired artifact, bad trading
key, Bybit regional refusal, or absent OI history.

## Prepared automatic acquisition

`acquire.py --output /workspace/hype-data --fetch` uses existing platform
authentication and normal proxy/CA configuration. It lists the exact requested
artifact identities, verifies optional GitHub publisher digests, records SHA-256
for all inputs, extracts ZIPs with traversal/symlink/size checks, and downloads the
official raw daily trade archive when that route is accessible. It also paginates
real Bybit 5-minute OI observations. Five-minute historical OI cannot supply true
30-second historical OI deltas. Full historical L2 book/liquidations remain a
separate unavailable source unless a verified archive is supplied; they cannot be
reconstructed from raw executed trades or OHLC.

The `HYPE-H1-LOCAL-V5-TICKS-*` workflow invokes `historical_ticks` in the existing
`research.py`, which aggregates raw trades to minute flow. Artifact names alone
do not prove that individual ordered raw trade records were retained. The
official daily raw archives are needed for within-minute ordering.

## Remaining external prerequisite

A draft allowlist addition for `api.github.com`, `public.bybit.com`,
`api.bybit.com`, `stream.bybit.com` was saved by the parent task. The configuration
tool explicitly reports that saving a draft neither applies it to this running
machine nor publishes it. There is no enabled tool here that can activate that
runtime network change. The parent task must distinguish draft persistence from
actual origin connectivity. Following a real policy update, rerun the acquisition
command; if the API then denies artifact access, diagnose scoped GitHub API
authentication separately from already-working Git access.

No proxy bypass, credential extraction, alternate-host impersonation, or invented
OI/book/liquidation data was used.
