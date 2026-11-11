import os
def capability_snapshot():
    return {"platform":"instagram","configured":{"meta":bool(os.getenv("META_ACCESS_TOKEN") and os.getenv("META_IG_USER_ID")),"instaloader_session":bool(os.getenv("IG_USERNAME") and (os.getenv("IG_SESSIONFILE") or os.getenv("IG_SESSION_B64")))}}
