import random

HOOK_STYLES = {
    "striking_number": "Open with the single most striking number in the data (e.g. a % move, a volume spike). No preamble before it.",
    "contradiction": "Open with a contradiction or tension in the data (e.g. price up but volume down, or two metrics disagreeing).",
    "direct_question": "Open with a direct question to the reader that the data below answers.",
    "scenario": "Open with a short relatable trading scenario (a position, a decision point) grounded in the data.",
    "comparison": "Open by comparing the current data point to a plain reference point (e.g. a round number, a recent level) using only the data given.",
}


def pick_hook_style(state, lookback=6):
    """
    Avoid repeating the same hook style as the last N published posts so the
    account doesn't read as templated. Falls back to uniform random.
    """
    recent = [
        p.get("hook_type") for p in state["posts"][-lookback:]
        if p.get("published") and p.get("hook_type")
    ]
    candidates = [h for h in HOOK_STYLES if h not in recent] or list(HOOK_STYLES.keys())
    return random.choice(candidates)


def hook_instruction(hook_style):
    return HOOK_STYLES.get(hook_style, HOOK_STYLES["striking_number"])


def hook_leaderboard(state):
    """
    Returns {hook_type: {"published": n, "avg_quality_score": x}} built from
    state history. This is a proxy leaderboard based on quality score and
    publish rate, not real engagement — Binance Square's OpenAPI does not
    expose per-post view/like metrics for pull, so true engagement-based
    A/B testing would need those numbers recorded separately if/when
    available.
    """
    stats = {}
    for post in state["posts"]:
        hook = post.get("hook_type")
        if not hook:
            continue
        entry = stats.setdefault(hook, {"attempts": 0, "published": 0, "score_sum": 0})
        entry["attempts"] += 1
        entry["score_sum"] += post.get("quality_score", 0)
        if post.get("published"):
            entry["published"] += 1
    for hook, entry in stats.items():
        entry["avg_quality_score"] = round(entry["score_sum"] / entry["attempts"], 1) if entry["attempts"] else 0
    return stats
