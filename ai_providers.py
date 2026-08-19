import os

from http_utils import request_with_retry, provider_available, record_provider_failure, record_provider_success

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openrouter/free"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


def _call_openai_style(name, api_key, url, model, system_prompt, user_prompt, max_tokens=400):
    if not api_key or not provider_available(name):
        return None
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        resp = request_with_retry("POST", url, headers=headers, json=payload)
        text = resp.json()["choices"][0]["message"]["content"].strip()
        record_provider_success(name)
        return text or None
    except Exception:
        record_provider_failure(name)
        return None


def call_groq(system_prompt, user_prompt):
    return _call_openai_style("groq", GROQ_API_KEY, GROQ_API_URL, GROQ_MODEL, system_prompt, user_prompt)


def call_openrouter(system_prompt, user_prompt):
    if not OPENROUTER_API_KEY or not provider_available("openrouter"):
        return None
    try:
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": OPENROUTER_MODEL,
            "max_tokens": 400,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "reasoning": {"exclude": True},
        }
        resp = request_with_retry("POST", OPENROUTER_API_URL, headers=headers, json=payload)
        text = resp.json()["choices"][0]["message"]["content"].strip()
        record_provider_success("openrouter")
        return text or None
    except Exception:
        record_provider_failure("openrouter")
        return None


def call_gemini(system_prompt, user_prompt):
    if not GEMINI_API_KEY or not provider_available("gemini"):
        return None
    try:
        headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }
        resp = request_with_retry("POST", GEMINI_API_URL, headers=headers, json=payload)
        parts = resp.json()["candidates"][0]["content"]["parts"]
        text = "\n".join(p["text"] for p in parts if p.get("text") and not p.get("thought")).strip()
        record_provider_success("gemini")
        return text or None
    except Exception:
        record_provider_failure("gemini")
        return None


def call_anthropic(system_prompt, user_prompt):
    if not ANTHROPIC_API_KEY or not provider_available("anthropic"):
        return None
    try:
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 400,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        resp = request_with_retry("POST", ANTHROPIC_API_URL, headers=headers, json=payload)
        result = resp.json()
        text = "\n".join(
            block["text"] for block in result.get("content", []) if block.get("type") == "text"
        ).strip()
        record_provider_success("anthropic")
        return text or None
    except Exception:
        record_provider_failure("anthropic")
        return None


PROVIDER_FUNCS = {
    "groq": call_groq,
    "gemini": call_gemini,
    "openrouter": call_openrouter,
    "anthropic": call_anthropic,
}


def call_in_order(order, system_prompt, user_prompt):
    for name in order:
        func = PROVIDER_FUNCS.get(name)
        if not func:
            continue
        result = func(system_prompt, user_prompt)
        if result:
            return result, name
    return None, None
