import os
import json
import time
import hashlib

_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")


def _empty_state():
    return {"posts": []}


def load_state():
    if not os.path.exists(_STATE_PATH):
        return _empty_state()
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _empty_state()


def save_state(state):
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def content_hash(text):
    normalized = " ".join(text.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_duplicate(state, text, window_days):
    h = content_hash(text)
    cutoff = time.time() - window_days * 86400
    for post in state["posts"]:
        if post["timestamp"] < cutoff:
            continue
        if not post.get("published"):
            continue
        if post.get("text_hash") == h:
            return True
    return False


def in_cooldown(state, field, value, hours):
    if not value:
        return False
    cutoff = time.time() - hours * 3600
    for post in state["posts"]:
        if post["timestamp"] < cutoff:
            continue
        if not post.get("published"):
            continue
        if post.get(field) == value:
            return True
    return False


def record_post(state, category, symbol, topic, text, ai_provider, data_snapshot,
                 quality_score, published, template_id=None):
    entry = {
        "timestamp": time.time(),
        "category": category,
        "symbol": symbol,
        "topic": topic,
        "text_hash": content_hash(text),
        "ai_provider": ai_provider,
        "data_snapshot": data_snapshot,
        "quality_score": quality_score,
        "published": published,
        "template_id": template_id,
    }
    state["posts"].append(entry)
    cutoff = time.time() - 30 * 86400
    state["posts"] = [p for p in state["posts"] if p["timestamp"] >= cutoff]
    save_state(state)
    return entry
