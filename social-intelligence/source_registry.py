"""Capability registry for supported social platforms.

The registry describes only features that can be implemented through official APIs
or verified public-page access. It deliberately does not claim access to hidden
activity, private communications, viewer lists, or full third-party social graphs.
"""
from __future__ import annotations

import os

CAPABILITIES = {
    "instagram": {
        "official_api": "Meta Instagram Graph API",
        "configured": bool(os.getenv("META_ACCESS_TOKEN")),
        "public_profile_link": True,
        "public_posts": "authorized_professional_accounts",
        "comments": "authorized_professional_accounts",
        "likes": "aggregate_or_owned_content_only",
        "followers_history": False,
        "following_history": False,
        "deleted_activity_history": False,
        "viewer_identity": False,
        "private_messages": False,
    },
    "vk": {
        "official_api": "VK API",
        "configured": bool(os.getenv("VK_ACCESS_TOKEN")),
        "public_profile_link": True,
        "public_posts": "subject_to_vk_api_visibility",
        "comments": "subject_to_vk_api_visibility",
        "likes": "object_scoped_where_api_allows",
        "followers_history": False,
        "following_history": False,
        "deleted_activity_history": False,
        "private_messages": False,
    },
    "telegram": {
        "official_api": "Telegram Bot API",
        "configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "public_profile_link": True,
        "public_channel_or_group_metadata": "bot_must_have_access",
        "public_messages": "only_in_chats_available_to_the_bot",
        "membership_checks": "specific_chat_only_and_permission_limited",
        "all_user_groups": False,
        "all_user_channels": False,
        "private_messages": False,
    },
}


def capability_snapshot() -> dict:
    return {"platforms": CAPABILITIES}
