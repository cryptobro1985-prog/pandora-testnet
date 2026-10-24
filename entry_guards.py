"""Publication-time freshness guard. No market-structure entry filter."""
import datetime
import email.utils


def publication_epoch(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        try:
            dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            dt = email.utils.parsedate_to_datetime(value)
        return dt.timestamp() if dt.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def freshness(published_at, current_epoch, max_age=120, future_tolerance=10):
    stamp = publication_epoch(published_at)
    if stamp is None:
        return {"allowed": False, "reason": "missing_publication_time", "age_seconds": None}
    age = current_epoch - stamp
    reason = ("future_publication_time" if age < -future_tolerance else
              "stale_news" if age > max_age else "fresh_news")
    return {"allowed": reason == "fresh_news", "reason": reason,
            "age_seconds": age, "max_age_seconds": max_age}


