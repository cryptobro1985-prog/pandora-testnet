# TECHNICAL PROMPT — Instagram Intelligence Combiner

Work only in:
- repo: cryptobro1985-prog/pandora-testnet
- branch: feature/social-intelligence-miniapp-mvp-20261111
- app root: social-intelligence/
- Render service: social-intelligence-live-v2
- public URL: https://social-intelligence-live-v2.onrender.com

Do NOT rebuild the old VK/Telegram product. This app is Instagram-only.

## User flow
One field accepts either @username or a direct Instagram profile URL. One button FULL SCAN. Return one consolidated report.

## Sources and exactly what to use

### 1. Meta Instagram Graph API / Business Discovery
Use existing Render environment names:
- META_ACCESS_TOKEN
- META_IG_USER_ID
- META_GRAPH_VERSION

Use Business Discovery for:
- username/name/biography/website
- profile_picture_url
- followers_count/follows_count/media_count
- media IDs, captions, timestamps, permalink, like_count, comments_count

Use /{media-id}/comments for:
- public comments returned by the API
- username/text/timestamp/like_count/replies

Never invent a list of liker usernames from aggregate like_count.

### 2. Instaloader
Upstream: https://github.com/instaloader/instaloader
License: MIT.

Install the package. Do not vendor the entire project.
Use these upstream concepts/APIs:
- instaloader/structures.py -> Profile.from_username
- Profile.get_posts()
- Profile.get_followers()
- Profile.get_followees()
- Post.get_comments()
- Post.get_likes()
- instaloader/instaloadercontext.py session/rate-limit behavior

Optional Render auth:
- IG_USERNAME
- IG_SESSIONFILE, or
- IG_SESSION_B64 containing a base64 Instaloader session file

Public collection must still work best-effort without a session.
Anything requiring login must return UNKNOWN/unavailable instead of fake zero.

### 3. igstalker
Upstream: https://github.com/JuaniVeltri/igstalker
License: MIT.

Do not copy its UI/product wholesale. Reuse/adapt the architecture ideas:
- packages/core/src/snapshot.ts -> immutable snapshot model
- packages/core/src/diff.ts -> set-based change detection between snapshots
- packages/core/src/scanner.ts -> scan orchestration
- packages/core/src/antiban.ts -> bounded retries / pacing concepts

Python implementation belongs inside social-intelligence.

## Required report

PROFILE
- username, name, avatar, bio, website
- followers, following, media count
- source and timestamp

CONTENT
- latest posts/reels available to collectors
- caption, permalink, timestamp
- aggregate likes/comments
- concrete commenter usernames when observable
- concrete liker usernames only when observable

INBOUND
- who comments on target
- who likes target where liker identity is exposed
- who mentions/tags target if a source actually exposes it

OUTBOUND
- accounts explicitly @mentioned by target in its own observed captions
- outgoing comments/likes only if directly observed from a legitimate public/authorized source
- never infer them from absence/presence elsewhere

RELATIONSHIPS
For each observed peer calculate:
- comments_in
- likes_in
- mentions_out
- total observed events
- weighted interaction score
Clearly label this as an analytical score, not a statement about personal closeness.

FOLLOWERS / FOLLOWING
If the authenticated collector exposes current lists:
- store snapshot
- compare to previous snapshot
- new_followers
- lost_followers
- new_following
- unfollowed
- repeated follow/unfollow can be reconstructed from accumulated snapshots

If lists are not exposed:
- return UNKNOWN
- do not convert UNKNOWN to []
- UI must visibly distinguish UNKNOWN from zero changes

PROFILE CHANGE HISTORY
Compare snapshots for:
- name
- bio
- website
- avatar URL
- follower/following counts
- media count

## Not observable
Never claim access to:
- identities of users who merely viewed the profile
- which profiles the target merely opened/viewed
- DMs/private messages
- private-account data without authorization

Display these as NOT OBSERVABLE rather than silently omitting them.

## Persistence
Use an event/snapshot store.
Preferred production backend: PostgreSQL.
Fallback for development only: SQLite.
Tables:
- accounts
- snapshots
- posts
- interactions
- relationship_scores
- scan_runs

Every record requires:
- username/target
- event type
- observed_at
- source
- source object ID/permalink where applicable
- confidence/observability marker

## Reliability
Collectors run independently and concurrently.
A failure in one collector must not fail the full scan.
Statuses:
- ok
- partial
- unavailable
- auth_required
- rate_limited
- not_observable

Use bounded timeouts/retries and cache recent scans.
Do not hammer Instagram.

## UI
Mobile-first premium dark Instagram analytics UI.
No VK/Telegram controls.
No person-name/phone/date-of-birth fields.
One search field.
Sections:
- Overview
- Relationships
- Followers changes
- Following changes
- Comments
- Likes
- Posts
- Timeline
- Sources / Coverage

UNKNOWN must be visually distinct from 0.

## Acceptance test
Before declaring done:
1. GET /api/health returns ok and service=instagram-intelligence.
2. UI contains Instagram Intelligence and no VK/Telegram analysis controls.
3. Run backend scan against a well-known public Instagram professional account such as @instagram.
4. Verify each returned item lands in the correct report section.
5. Verify aggregate like_count is never presented as concrete liker identities.
6. Run the same target twice and verify snapshot history exists.
7. If follower/following lists are available, diff must be set-based and deterministic.
8. If unavailable, UI must show UNKNOWN rather than 0.
9. Check Render logs for startup exceptions/5xx.
10. Keep all existing Render secrets; never commit secrets.
