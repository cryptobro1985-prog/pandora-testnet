# Social Intelligence Mini App (safe MVP)

This is an independent module in the Pandora repository, built in an isolated feature branch. It **does not** operate the trading bots or modify the HYPE research branch.

## What works today

- Responsive Russian-language Telegram Mini App-style page with optional name, birth date, birth city, phone number, social profile URLs and local photo preview.
- Consent/authorization checkbox.
- Browser-local organization of provided social links, platform tabs, progress and source status.
- Optional FastAPI backend (`/api/analyze`) that validates submitted public profile links; unit tests and GitHub Actions package the static UI.
- No fabricated followers, likes, memberships, messages, location data or social graph.

## What is not implemented

- There is **no automated cross-platform people search**, platform API connector, historical like/follow tracking, scraping, facial identification, dating-account detection or public deployment.
- The user checking a checkbox is not evidence that a third party consented to profiling.
- No uploaded files or phone numbers are transmitted by this MVP; optional identity inputs remain in browser memory.
- GitHub Actions runs tests and produces an artifact. It is not a persistent backend and **does not** mean the Telegram bot has been attached.

## Run locally

```bash
cd social-intelligence
python -m pip install -r requirements.txt
uvicorn app:app --reload
```

Open http://127.0.0.1:8000/ . Run tests with `pytest -q tests`.

## Deploying to Telegram

1. Deploy an HTTPS frontend, and if needed the FastAPI service, to a suitable host. GitHub Actions alone does not host a long-lived API.
2. Create or select a bot in BotFather; set its Mini App/Web App URL to the HTTPS page.
3. Before production, implement Telegram initData verification in the backend (server-side using a token in host secrets), access control, retention policy and permitted connector APIs.
4. Do not commit bot tokens, API keys, personal records, phone numbers or photos. Rotate any previously exposed bot token.
5. For authorized professional-account analytics, add official API connectors with explicit scope and platform-compliant rate limiting; show availability rather than inventing missing activity.

## Purpose and boundaries

This module organizes publicly supplied profile links and can evolve into an authorized analytics service for accounts managed by the user or verified professional organizations. It must not be used to create detailed tracking dossiers about private individuals, discover secret dating accounts, infer private social relations, or obtain addresses/location trails.
