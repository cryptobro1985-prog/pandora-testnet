# Instagram Intelligence Super-Combiner

Instagram-only mini app. Input: `@username` or an Instagram profile URL. Output: one consolidated report built from multiple independent collectors.

## Open-source components used

- **instaloader/instaloader (MIT)** — profile/posts/comments/visible liker identities and authenticated follower/following collection when the configured session permits it.
- **2scraper/instagram-scraper (MIT)** — adapted server-rendered `<script type="application/json">` parsing patterns for logged-out public profiles and post/Reel metadata: exact follower/following counts, captions, hashtags, mentions, tags, coauthors and locations when Instagram serves them.
- **JuaniVeltri/igstalker (MIT)** — adapted snapshot/scanner/diff architecture and stable-`pk` identity principle so username changes do not become false unfollow/follow events.
- **mohammedelahmar/InstaTrack** — adapted audience-engagement / ghost-candidate analysis concept. Results are emitted only when both follower identities and engagement identities were actually observed.
- **ignromanov/safe-unfollow (MIT)** — adapted relationship badge model: follower, following, mutual, not-following-back, not-followed-back.

The original repositories remain the source of their respective implementations/concepts. This project does not claim access to data Instagram does not expose.

## Pipeline

Collectors run independently and concurrently:
1. public page fallback (OpenGraph)
2. public embedded JSON collector
3. Meta Business Discovery / comments when configured
4. Instaloader collector

They are merged into one normalized report:
- PROFILE
- POSTS / REELS
- INBOUND interactions
- OUTBOUND observed interactions
- RELATIONSHIP SCORES
- FOLLOWERS / FOLLOWING snapshots and diffs
- AUDIENCE QUALITY
- RELATIONSHIP GRAPH
- TIMELINE
- SOURCE COVERAGE

## Truth rules

- `UNKNOWN != 0`.
- Aggregate `like_count` is never converted into liker identities.
- Follow/unfollow is only reported from two actually observed snapshots.
- Snapshot diffs use stable Instagram user IDs when available, not username alone.
- Profile-viewer identities, another person's browsing history and private DMs are not observable through these collectors and are never fabricated.
- Outgoing likes/comments are shown only when directly observed by an enabled legitimate source.

## Render

Existing service: `social-intelligence-live-v2`

Health: `/api/health`
Capabilities: `/api/capabilities`
Live backend acceptance check: `/api/smoke`
History: `/api/history/{username}`

Optional environment variables:
- `META_ACCESS_TOKEN`
- `META_IG_USER_ID`
- `META_GRAPH_VERSION`
- `IG_USERNAME`
- `IG_SESSIONFILE` or `IG_SESSION_B64`
- `IG_INTEL_DB`
- `IG_STARTUP_SMOKE_TARGET`
