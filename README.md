# Pandora paper news engine

The engine remains PAPER_ONLY and reads Hyperliquid testnet prices. This is a
paper execution study, not an exchange account or a claim of trading returns.

## Entry decisions

- Direction comes from a fresh news/post event. There is no market-structure
  alignment gate and no wait for a new candle or trend confirmation.
- `NEWS_MAX_AGE_SECONDS` defaults to **120 seconds from publication**, not from
  receipt by an index/RSS reader. Missing, malformed, naive or future timestamps
  are rejected and journalled. Freshness is rechecked immediately before entry.
- Market features are cached, advisory research metadata, not entry vetoes.
  Optional external context requests never run in the entry or exit path.
- Each configured RSS source has its own worker; the default poll interval is
  10 seconds (`NEWS_POLL_SECONDS`). One failed source cannot delay the others.
- Official X access requires `X_BEARER_TOKEN`. Google indexes and RSS discovery
  fallbacks have publisher/indexing delays and are explicitly labelled as such;
  polling them faster cannot guarantee instant or complete social coverage.
- A fresh event still may be skipped for no directional signal, no tradable
  symbol, stale prices, an existing position, unavailable engine lease or margin.

## Durable exits

Every successful market cycle commits the position's peak, trailing activation,
monotonic trailing stop, last quote/evaluation and recent price history to Neon.
Legacy positions recover their observed extreme/history from stored snapshots
on takeover. Their existing leverage and margin are preserved.

Profit protection arms at 10% gross ROE and protects 7.5%; trailing arms at 12%
gross ROE with the existing bounded volatility gap. An armed stop executes when
crossed, without an additional weakening gate. Stops never loosen. After a
quote gap, paper exits use the **current observed price**, not a fictitious fill
at yesterday's stop/minimum. Gross ROE thresholds are not net profit guarantees.

Closing the position, crediting the paper account and writing the trade/audit
record are one transaction. Retried closes cannot credit twice; a checkpoint
UPDATE cannot resurrect a closed position. In-memory account state changes only
after the transaction commits.

A renewable 30-second database lease fences every position write. Rolling
deploys therefore have one writer. The first migration from the old lease-less
release waits 120 seconds for Render's legacy process drain; subsequent takeovers
wait only for lease release/expiry. SIGTERM stops new work and releases ownership.

## Health and hosting

- `/health`: fast liveness endpoint, no database or external API calls.
- `/health/risk`: returns 200 only with an active writer, fresh prices and a
  recent committed checkpoint; otherwise 503. Standby is not trading-ready.
- `/api/dashboard`: includes engine state, checkpoints, peak and active stops.
  Dashboard database reads and optional telemetry do not hold the risk lock.
- Entry and exit processing are independent of whether a user views the monitor.

**Render Free still sleeps.** The code cannot turn a sleeping free web service
into guaranteed 24/7 compute. Use the existing service's paid always-on compute
plan to remove idle sleeping. The existing GitHub wake schedule is best-effort,
not an uptime guarantee. Changing hosting plans can add charges and is a separate
deployment configuration action; code deployment does not silently upgrade it.

Keep the existing Neon `DATABASE_URL`; do not import an old blueprint to create
a second database. Additive schema migrations run at application startup and
leave account/trade/news history intact. Do not roll back to the old unfenced
writer while this version owns the database lease.

## Validation

```bash
python -m pip install "psycopg[binary]>=3.2,<4"
python -m unittest discover -s tests -v
```

Unit tests cover the NOT minimum/restart, protection without history, monotonic
long/short trailing, old CoinShares news and fresh counter-trend news. Database
tests additionally run when `PANDORA_TEST_DATABASE_URL_FILE` names a file holding
the URL of an **isolated** database. Never point these tests at the live account.
The GitHub workflow provisions disposable PostgreSQL for all integration tests.
`tests/storage_contract.sql` separately validates the SQL contract on an isolated
Neon branch. No test should modify the live trading study's history or balance.

### Free direct social readers

Sources: https://github.com/vladkens/twscrape (0.20.1, MIT) and
https://github.com/w2rc/truthbrush (PyPI 0.3.0, Apache-2.0).
Both run in independent subprocesses with 35-second hard deadlines so a blocked
source cannot stall exits. XScrape polls every 5 seconds after a completed request;
Truthbrush every 10 seconds, with backoff on errors. These are polling readers,
not guaranteed sub-second feeds. Existing RSS/search readers remain as fallbacks.
The same canonical event IDs deduplicate the direct and existing API readers;
the existing publication-age guard still applies at ingestion and entry.

X needs an authorized account session: set `X_SESSION_COOKIES` as a secret in the
hosting environment, containing `auth_token` and `ct0` from your own X session.
Do not send cookies in chat or commit them. twscrape's temporary SQLite session
store is rebuilt from that secret after restart. Telemetry is disabled.
Truthbrush tries public endpoints; optional `TRUTHSOCIAL_TOKEN` can be configured
as a hosting secret. Do not assume a token resolves a network restriction.
No passwords, automatic account creation, purchased accounts or paid APIs needed.
If credentials are absent or the platform returns 403, the dashboard reports
`ok:false` with a reason rather than claiming the source is scanning.
No claim of working live X ingestion until an authorized session returns posts.

### Public readers without X sessions (October 24 follow-up)

`public_social.py` parses public X profile HTML and decodes embedded JSON as data,
never JavaScript execution. It preserves the post ID, author and original timestamp,
rejects sign-in/changed-schema pages and excludes nested quotes as new signals.
Each watched account has an independent worker: 12-second HTTP timeout, 10-second
wait after completion, bounded exponential backoff (at least 60 seconds on 429).
This is best-effort polling, NOT verified instant delivery or complete X coverage.
`XPublic:<handle>` reports page retrieval and newest visible post age separately.
The actual publication-age guard still blocks old posts at entry.

`TruthArchive` reads https://www.trumpstruth.org/feed?limit=20 without credentials,
with original RSS publication timestamps and a 30-second wait after completion.
It covers Trump's archived text posts only; image-only entries are excluded.
Archive indexing latency is unknown; `realtime_verified` remains false.

Live research probes: X public HTML yielded authored posts with original timestamps;
X guest GraphQL returned HTTP 200 but mostly old/popular posts, so it is NOT wired
as a live signal source. Public embed timeline returned 429. Direct Truth statuses
and streaming-health returned 403; public profile is an HTML app shell, not posts.
Do not confuse HTTP 200 or an old latest post with measured delivery latency.
Research: https://github.com/DevamShah/pravaha,
https://github.com/tamnd/x-cli, https://github.com/ythx-101/x-tweet-fetcher.
