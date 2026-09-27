import re
from difflib import SequenceMatcher

from ai_providers import call_in_order
from prompts import WRITER_SYSTEM_PROMPT, EDITOR_SYSTEM_PROMPT, build_context
from validator import clean_text, basic_validate, fact_check, check_whale_claim_grounded
from config_loader import load_config
from hooks import hook_instruction


def generate_post(trusted_data_text, data_snapshot, untrusted_text="", allow_cashtag=True,
                   hook_style=None, whale_data_provided=False, recent_posts=None):
    cfg = load_config()
    provider_order = cfg["providers"]["order"]
    posting_cfg = cfg["posting"]

    context = build_context(trusted_data_text, untrusted_text)
    if hook_style:
        context = f"HOOK STYLE FOR THIS POST: {hook_instruction(hook_style)}\n\n{context}"

    draft, provider = call_in_order(provider_order, WRITER_SYSTEM_PROMPT, context)
    if not draft:
        return None

    editor_input = f"DRAFT:\n{draft}\n\n{context}"
    edited, _ = call_in_order(provider_order, EDITOR_SYSTEM_PROMPT, editor_input)
    final_text = edited or draft

    final_text = clean_text(final_text, allow_cashtag)

    ok, reason = basic_validate(
        final_text,
        max_lines=posting_cfg["max_lines"],
        max_hashtags=posting_cfg["max_hashtags"],
        max_emojis=posting_cfg["max_emojis"],
    )
    if not ok:
        print(f"⚠️ Rejected by validator ({reason}). Raw text was:\n---\n{final_text}\n---")
        return {"text": None, "provider": provider, "reject_reason": reason}

    fact_ok, fact_reason = fact_check(final_text, data_snapshot)
    if not fact_ok:
        print(f"⚠️ Rejected by fact-check ({fact_reason}). Raw text was:\n---\n{final_text}\n---")
        return {"text": None, "provider": provider, "reject_reason": fact_reason}

    whale_ok, whale_reason = check_whale_claim_grounded(final_text, whale_data_provided)
    if not whale_ok:
        print(f"⚠️ Rejected ({whale_reason}). Raw text was:\n---\n{final_text}\n---")
        return {"text": None, "provider": provider, "reject_reason": whale_reason}

    score = score_post(final_text, data_snapshot, recent_posts=recent_posts)

    return {
        "text": final_text,
        "provider": provider,
        "reject_reason": None,
        "quality_score": score,
        "hook_style": hook_style,
    }


def _structural_fingerprint(text):
    """
    Reduce a post to its structural shape, ignoring the actual numbers/symbols,
    so two posts that are 'different numbers, same skeleton' are recognized
    as similar.
    """
    normalized = text.lower()
    normalized = re.sub(r"\$[a-z]+", "$SYM", normalized)          # $SOL -> $SYM
    normalized = re.sub(r"#\w+", "#TAG", normalized)               # #trading -> #TAG
    normalized = re.sub(r"-?\d+(\.\d+)?%", "PCT", normalized)      # 3.478% -> PCT
    normalized = re.sub(r"\d[\d,]*(\.\d+)?", "NUM", normalized)    # any other number -> NUM
    normalized = " ".join(normalized.split())
    return normalized


def _similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()


def score_post(text, data_snapshot, recent_posts=None, similarity_lookback=8,
               similarity_penalty_max=35, similarity_threshold=0.55):
    score = 60
    if any(ch.isdigit() for ch in text):
        score += 10
    if "?" in text:
        score += 5
    lines = [l for l in text.split("\n") if l.strip()]
    if 1 <= len(lines) <= 4:
        score += 10
    if data_snapshot:
        score += 5

    if recent_posts:
        fp_new = _structural_fingerprint(text)
        recent_texts = [
            p.get("text_for_similarity") or p.get("text", "")
            for p in recent_posts[-similarity_lookback:]
            if p.get("published")
        ]
        if recent_texts:
            best_match = max(
                _similarity(fp_new, _structural_fingerprint(t))
                for t in recent_texts
            )
            if best_match > similarity_threshold:
                # كلما اقترب البوست الجديد من بوست سابق هيكليًا، زادت العقوبة
                overshoot = (best_match - similarity_threshold) / (1 - similarity_threshold)
                penalty = round(similarity_penalty_max * overshoot)
                score -= penalty

    return min(max(score, 0), 100)
