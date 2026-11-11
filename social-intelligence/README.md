# Instagram Intelligence Mini App

Instagram-only service.

Input: @username or Instagram profile URL.

Outputs: public/authorized profile data, posts, comments, visible liker identities when exposed, follower/following snapshots when exposed, follow/unfollow diffs between consecutive observed snapshots, and interaction ranking.

Sources:
- Meta Instagram Graph API / Business Discovery using existing META_ACCESS_TOKEN and META_IG_USER_ID.
- Instaloader (MIT) for public/profile/post collection and optional authenticated session.
- Public Instagram profile page as fallback.

Optional env: IG_USERNAME plus IG_SESSIONFILE or IG_SESSION_B64. IG_INTEL_DB controls local snapshot DB path.

The app never fabricates profile viewer identities or another user's profile browsing history because Instagram does not expose those to this collector.
