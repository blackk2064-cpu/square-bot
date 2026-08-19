import re

from prompts import BANNED_SNIPPETS


def clean_text(text, allow_cashtag):
    if not text:
        return text
    # Fix reversed cashtags/hashtags: "SOL$" -> "$SOL", "trading#" -> "#trading"
    text = re.sub(r"\b([A-Za-z]{2,10})\$", r"$\1", text)
    text = re.sub(r"\b([A-Za-z]{2,15})#", r"#\1", text)
    text = re.sub(r"#\s+", "#", text)
    text = re.sub(r"\$\s+([A-Z])", r"$\1", text)
    text = re.sub(r"(#\w+)(?=#)", r"\1 ", text)
    if not allow_cashtag:
        text = re.sub(r"\$[A-Z]{2,10}\b", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def basic_validate(text, max_lines=6, max_hashtags=2, max_emojis=2, max_chars=480):
    if not text:
        return False, "empty"
    stripped = text.strip()
    if len(stripped) < 15:
        return False, "too_short"
    if len(stripped) > max_chars:
        return False, "too_long"
    lowered = stripped.lower()
    for snippet in BANNED_SNIPPETS:
        if snippet in lowered:
            return False, f"banned_snippet:{snippet}"
    if re.match(r"^\s*\d+\.\s*(analysis|thinking|reasoning|plan)\b", lowered):
        return False, "looks_like_reasoning_list"

    sentence_count = len(re.findall(r"[.!?]+", stripped))
    word_count = len(stripped.split())
    if sentence_count >= 4 and word_count > 60:
        return False, "too_many_sentences_for_a_post"

    lines = [l for l in stripped.split("\n") if l.strip()]
    if len(lines) > max_lines:
        return False, "too_many_lines"

    hashtags = re.findall(r"#\w+", stripped)
    if len(hashtags) > max_hashtags:
        return False, "too_many_hashtags"

    emoji_pattern = re.compile(
        "[\U0001F300-\U0001FAFF\U00002600-\U000027BF]"
    )
    emojis = emoji_pattern.findall(stripped)
    if len(emojis) > max_emojis:
        return False, "too_many_emojis"

    return True, "ok"


def _extract_numbers(text):
    return set(re.findall(r"-?\d+(?:\.\d+)?", text))


def fact_check(text, data_snapshot, tolerance=0.05):
    """
    Compares numeric percentage/price claims in the generated text against
    the trusted data snapshot. Returns (passed, reason). Conservative: only
    flags a hard mismatch when a number in the text looks like a percent or
    price that doesn't correspond to anything in the snapshot within
    tolerance.
    """
    if not data_snapshot:
        return True, "no_data_to_check"

    known_values = set()
    for sym, fields in data_snapshot.items():
        for key, val in fields.items():
            if isinstance(val, (int, float)):
                known_values.add(round(val, 2))
                known_values.add(round(val, 1))
                known_values.add(round(val, 0))

    percent_claims = re.findall(r"(-?\d+(?:\.\d+)?)\s?%", text)
    for claim in percent_claims:
        try:
            claim_val = float(claim)
        except ValueError:
            continue
        matched = False
        for known in known_values:
            if abs(claim_val - known) <= max(tolerance * abs(known), 0.15):
                matched = True
                break
        if not matched:
            return False, f"unmatched_percent_claim:{claim}"

    return True, "ok"
