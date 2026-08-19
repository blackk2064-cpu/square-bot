from ai_providers import call_in_order
from prompts import WRITER_SYSTEM_PROMPT, EDITOR_SYSTEM_PROMPT, build_context
from validator import clean_text, basic_validate, fact_check
from config_loader import load_config


def generate_post(trusted_data_text, data_snapshot, untrusted_text="", allow_cashtag=True):
    cfg = load_config()
    provider_order = cfg["providers"]["order"]
    posting_cfg = cfg["posting"]

    context = build_context(trusted_data_text, untrusted_text)

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

    score = score_post(final_text, data_snapshot)

    return {
        "text": final_text,
        "provider": provider,
        "reject_reason": None,
        "quality_score": score,
    }


def score_post(text, data_snapshot):
    score = 60
    if any(ch.isdigit() for ch in text):
        score += 15
    if "?" in text:
        score += 10
    lines = [l for l in text.split("\n") if l.strip()]
    if 1 <= len(lines) <= 4:
        score += 10
    if data_snapshot:
        score += 5
    return min(score, 100)
