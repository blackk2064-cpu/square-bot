#!/usr/bin/env python3
"""
Binance Square Auto-Poster Bot
================================
Fetches live market data / news / announcements from public APIs and posts
an auto-generated English update to Binance Square using the official
Square OpenAPI (X-Square-OpenAPI-Key).

Content is written by a 5-station free-AI pipeline (Cerebras -> Groq ->
Gemini -> OpenRouter -> GitHub Models), with every output run through a
code-level validator before it's ever allowed to post -- this catches
leaked "thinking" text, safety-filter messages, or other non-post garbage
that a model occasionally returns instead of the actual post.

Run once per invocation — scheduled hourly via GitHub Actions.

Required environment variable:
    SQUARE_OPENAPI_KEY   -> your Binance Square OpenAPI key (Creator Center)
"""

import os
import random
import sys
import time
import re
import subprocess
import xml.etree.ElementTree as ET
import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SQUARE_POST_URL = "https://www.binance.com/bapi/composite/v1/public/pgc/openApi/content/add"

# Unrestricted mirror for public spot market data (api.binance.com blocks
# requests from US-hosted servers, incl. GitHub Actions, with HTTP 451).
SPOT_TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"

# Futures data has no unrestricted mirror — fetched best-effort.
FAPI_FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
FAPI_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"

# Free public news feed, no API key required.
NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"

# Official RSS feeds — free, legitimate syndication (not scraping).
RSS_SOURCES = {
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "The Block": "https://www.theblock.co/rss.xml",
}

# Macro-economic news (Fed, CPI, jobs, GDP, geopolitics, earnings) that
# moves crypto/markets broadly, separate from crypto-native headlines.
MACRO_RSS_SOURCES = {
    "MarketWatch": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
}

# NOTE: this is an *unofficial* internal endpoint used by binance.com's own
# website to render its announcements page. It is not part of Binance's
# documented developer API, has no stability guarantee, and has been known
# to return 403 without warning. Treated as best-effort like funding data.
BAPI_ANNOUNCE_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
CATALOG_NEW_LISTING = 48
CATALOG_DELISTING = 161

SYMBOLS = ["BTC", "ETH", "SOL", "BNB"]

CATEGORY_WEIGHTS = {
    "binance_news": 20,
    "general_news": 14,
    "macro_news": 15,
    "analysis": 17,
    "education": 13,
    "sarcastic": 13,
    "events": 8,
}

API_KEY = os.environ.get("SQUARE_OPENAPI_KEY")
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SquareBot/1.0)"}

# --- AI content generation (optional — falls back to static templates) ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

AI_SYSTEM_PROMPT = """You are a professional Binance Square content creator with a track record
of high-reach posts. Write ONE Binance Square post using the live market
data provided in the user message.

FORMAT RULES:
- Only include a cashtag (e.g. "$BTC") if a specific coin/symbol is named
  in the data provided. Never invent or guess a symbol that isn't in the
  data -- a post with no symbol in the data should have NO cashtag at all.
  When you do include one, write it as a standalone token on its own line
  or clause, never attached to a dollar amount (correct: "$BTC" ...
  "trading near $64,200" -- wrong: "$64,200 BTC").
- Two content shapes are equally valid -- pick whichever fits the data:
  (a) Short-form: 1-3 lines total, just the cashtag + a terse data point
      (price ladder, a single striking number, a yes/no setup).
  (b) Long-form: 80-180 words, hook-first opening line, short paragraphs
      (1-2 lines each), grounded in the data given, ending with a genuine
      question inviting a reply.
- Never fabricate a news event, quote, price, or percentage that isn't in
  the data provided. If the data is thin, prefer the short-form shape
  instead of padding with generic filler.
- No more than 2 hashtags. Each hashtag must be written with NO space
  between the "#" and the word right after it, and exactly one space
  separating one hashtag from the next (correct: "#trading #education" --
  wrong: "#trading#education" and wrong: "# trading # education").
  No more than 2 emoji per post.
- Do not sound like generic AI copy -- avoid "In today's fast-paced crypto
  world", stock disclaimers beyond one short risk line, and clickbait that
  isn't backed by the actual data.
- If the data includes a real current event, you may frame it as a live,
  unfolding situation -- but only using the facts given, never invented ones.
- End most posts with a specific, answerable question (not a generic
  "thoughts?") -- e.g. "Bullish or bearish if it clears $65k?" rather than
  "What do you think?".
- CRITICAL: Output ONLY the literal final post text. Never include your
  reasoning, analysis of the request, step-by-step thinking, rule
  restatement, or any meta-commentary about what you're about to write.
  The very first character of your reply must be the first character of
  the post itself.

Return ONLY the final post text, nothing else -- no preamble, no quotation
marks around it, no explanation."""


# ---------------------------------------------------------------------------
# Output validator — the real safety net. Runs on every AI response before
# it's allowed anywhere near post_to_square(). Catches leaked reasoning
# traces, safety-filter messages, and other non-post garbage that a model
# occasionally returns instead of following the system prompt.
# ---------------------------------------------------------------------------

BANNED_SNIPPETS = [
    "<think", "</think", "chain of thought", "chain-of-thought",
    "تحليل الطلب", "قواعد التنسيق", "سلامة المستخدم", "إليك عملية تفكير",
    "here's my thinking", "let me think", "let me analyze", "i need to write",
    "i'll write", "step 1:", "step 1.", "1. تحليل", "format rules:",
    "hook line", "closing question:", "strategist's angle", "critic's verdict",
    "user safety", "safety: safe", "content filter", "as an ai",
    "i cannot", "i can't help with that",
]


def validate_post_text(text: str) -> bool:
    """Returns False if the text looks like leaked reasoning, a safety
    message, or anything else that isn't an actual finished post."""
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) < 15:
        return False
    lowered = stripped.lower()
    for snippet in BANNED_SNIPPETS:
        if snippet in lowered:
            print(f"🚫 AI output rejected — contained banned snippet: '{snippet}'")
            return False
    # A real post shouldn't be mostly numbered meta-lines like "1. Analysis: ..."
    if re.match(r"^\s*\d+\.\s*(analysis|thinking|reasoning|plan)\b", lowered):
        print("🚫 AI output rejected — looked like a numbered reasoning list.")
        return False
    return True


# Groq (free tier, no credit card, ~1000 req/day) — tried first since it
# costs nothing. Anthropic is tried second if a key is provided (small
# per-post cost, ~$0.01). If neither key is set or both fail, the caller
# falls back to a static template.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"


def generate_with_groq(context: str) -> str:
    if not GROQ_API_KEY:
        return None
    try:
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": GROQ_MODEL,
            "max_tokens": 400,
            "messages": [
                {"role": "system", "content": AI_SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
        }
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        return text or None
    except Exception as e:
        print(f"⚠️ Groq generation failed ({e}).")
        return None


def generate_with_anthropic(context: str) -> str:
    if not ANTHROPIC_API_KEY:
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
            "system": AI_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": context}],
        }
        resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        result = resp.json()
        text = "\n".join(
            block["text"] for block in result.get("content", []) if block.get("type") == "text"
        ).strip()
        return text or None
    except Exception as e:
        print(f"⚠️ Anthropic generation failed ({e}).")
        return None


def clean_ai_text(text: str, allow_cashtag: bool) -> str:
    """
    Enforces formatting rules in code instead of trusting the model to
    follow them perfectly every time (small free models are inconsistent
    about spacing and can ignore "don't invent a symbol" instructions).
    """
    if not text:
        return text

    text = re.sub(r"#\s+", "#", text)          # "# word" -> "#word"
    text = re.sub(r"(#\w+)(?=#)", r"\1 ", text)  # "#a#b" -> "#a #b"

    if not allow_cashtag:
        text = re.sub(r"\$[A-Z]{2,10}\b", "", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

    return text


def call_groq(system_prompt: str, user_prompt: str) -> str:
    if not GROQ_API_KEY:
        return None
    try:
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": GROQ_MODEL,
            "max_tokens": 400,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip() or None
    except Exception as e:
        print(f"⚠️ Groq call failed ({e}).")
        return None


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def call_gemini(system_prompt: str, user_prompt: str) -> str:
    if not GEMINI_API_KEY:
        return None
    try:
        headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            # Explicitly disable "thinking" — Gemini 2.5 models can emit an
            # internal reasoning trace by default, which previously leaked
            # into the published post when we only read parts[0].
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }
        resp = requests.post(GEMINI_API_URL, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        parts = resp.json()["candidates"][0]["content"]["parts"]
        # Join every non-thought text part (defense in depth, in case
        # thinkingBudget=0 isn't honored for some model/account combo).
        text = "\n".join(p["text"] for p in parts if p.get("text") and not p.get("thought")).strip()
        return text or None
    except Exception as e:
        print(f"⚠️ Gemini call failed ({e}).")
        return None


STRATEGIST_PROMPT = (
    "You are a Binance Square content strategist. Given the market data below, "
    "pick the single most compelling angle for a post -- the one specific number, "
    "contrast, or development worth leading with. Reply in 2-3 short sentences: "
    "state the angle and why it's the strongest choice. Do not write the post itself."
)

CRITIC_PROMPT = (
    "You are a blunt content critic for Binance Square. You'll get the market data "
    "and a strategist's proposed angle. If the angle is cliche, generic, or doesn't "
    "use the specific numbers well, say so and propose a sharper alternative in 1-2 "
    "sentences. If it's genuinely strong, say so briefly and confirm it. Do not write "
    "the post itself -- just the critique/verdict."
)

WRITER_PROMPT = AI_SYSTEM_PROMPT + """

You will receive: the raw data, a strategist's angle, and a critic's verdict.
Follow this exact structure and these hard rules:

1. HOOK (first line, 10 words or fewer): must contain a striking number, a
   contradiction, or a personal/relatable scenario. Never open with a known
   fact or a textbook definition (bad: "Leverage multiplies gains and
   losses." -- good: "A 5% move with 20x leverage wipes your position.").
2. BODY (1-2 sentences): the specific data, stated cleanly. At least one
   concrete number must appear somewhere in the post -- numbers build
   instant credibility, vague language doesn't.
3. YOUR READ (1 sentence): why this matters, or what it usually means. This
   is where personality shows -- not just relaying information.
4. CLOSING QUESTION: exactly two clear, concrete options to pick between,
   answerable in a few seconds (bad: "What do you think?" -- good: "5x with
   room to breathe, or 50x and hope?").

Hard limits: 4 short lines maximum (blank lines between them are fine and
encouraged for readability, but don't exceed 4 lines of actual content).
Never reuse the same opening pattern as recent posts -- vary the hook style
even when the underlying idea repeats (e.g. don't always start with
"Notice how...")."""


CEREBRAS_API_KEY = os.environ.get("CEREBRAS_API_KEY")
CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"
CEREBRAS_MODEL = "llama-3.3-70b"


def call_cerebras(system_prompt: str, user_prompt: str) -> str:
    if not CEREBRAS_API_KEY:
        return None
    try:
        headers = {"Authorization": f"Bearer {CEREBRAS_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": CEREBRAS_MODEL,
            "max_tokens": 300,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        resp = requests.post(CEREBRAS_API_URL, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip() or None
    except Exception as e:
        print(f"⚠️ Cerebras call failed ({e}).")
        return None


OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "openrouter/free"


def call_openrouter(system_prompt: str, user_prompt: str) -> str:
    if not OPENROUTER_API_KEY:
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
            # Ask providers that support it to exclude chain-of-thought
            # reasoning tokens from the content field. Ignored harmlessly
            # by models/providers that don't support it.
            "reasoning": {"exclude": True},
        }
        resp = requests.post(OPENROUTER_API_URL, headers=headers, json=payload, timeout=25)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip() or None
    except Exception as e:
        print(f"⚠️ OpenRouter call failed ({e}).")
        return None


GH_MODELS_TOKEN = os.environ.get("GH_MODELS_TOKEN")
GITHUB_MODELS_API_URL = "https://models.github.ai/inference/chat/completions"
GITHUB_MODELS_MODEL = "openai/gpt-4.1"


def call_github_models(system_prompt: str, user_prompt: str) -> str:
    if not GH_MODELS_TOKEN:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {GH_MODELS_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        }
        payload = {
            "model": GITHUB_MODELS_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        resp = requests.post(GITHUB_MODELS_API_URL, headers=headers, json=payload, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        # If the response was content-filtered, don't treat whatever's left
        # in `content` as usable text.
        if choice.get("finish_reason") == "content_filter":
            print("⚠️ GitHub Models response was content-filtered, discarding.")
            return None
        return (choice["message"]["content"] or "").strip() or None
    except Exception as e:
        print(f"⚠️ GitHub Models call failed ({e}).")
        return None


ANALYST_PROMPT = (
    "You are a fast data analyst for a Binance Square bot. Given raw market "
    "data, extract the 2-3 most noteworthy facts as short bullet points -- "
    "no commentary, no opinions, just the sharpest, most specific facts a "
    "content writer could build a post around."
)

EDITOR_PROMPT = AI_SYSTEM_PROMPT + """

You are the final editor. You'll receive a draft post. Check it against
every rule above (cashtag usage, hashtag formatting, hook under 10 words,
at least one concrete number, 4-line max, two-option closing question) and
fix anything that's off. If the draft already follows every rule, return it
unchanged. Return ONLY the final post text -- nothing else. Never return
anything other than the post itself, even a safety note or disclaimer
about the request."""


def discuss_and_write(context: str) -> str:
    """
    Runs the 5-station discussion pipeline (Analyst -> Strategist -> Critic
    -> Writer -> Editor) across Cerebras/Groq/Gemini/OpenRouter/GitHub
    Models. Degrades gracefully: if a step's model is unavailable, that
    step is skipped rather than blocking the whole pipeline. Returns None
    only if the Writer step itself fails on every provider.
    """
    insights = call_cerebras(ANALYST_PROMPT, context)
    working_context = f"{context}\n\nKEY INSIGHTS:\n{insights}" if insights else context

    angle = call_groq(STRATEGIST_PROMPT, working_context) or call_gemini(STRATEGIST_PROMPT, working_context)

    critique = None
    if angle:
        critic_input = f"DATA:\n{working_context}\n\nSTRATEGIST'S ANGLE:\n{angle}"
        critique = call_gemini(CRITIC_PROMPT, critic_input) or call_groq(CRITIC_PROMPT, critic_input)

    writer_input = f"DATA:\n{working_context}"
    if angle:
        writer_input += f"\n\nSTRATEGIST'S ANGLE:\n{angle}"
    if critique:
        writer_input += f"\n\nCRITIC'S VERDICT:\n{critique}"

    draft = call_openrouter(WRITER_PROMPT, writer_input) or call_groq(WRITER_PROMPT, writer_input) or call_gemini(WRITER_PROMPT, writer_input)
    if not draft:
        return None

    edited = call_github_models(EDITOR_PROMPT, draft)
    return edited or draft


def generate_with_ai(context: str, allow_cashtag: bool = True) -> str:
    """
    Tries the multi-step discussion pipeline first (free providers), then a
    single-shot call (Groq, then Anthropic if a paid key is set). Every
    candidate is cleaned and then validated -- if it fails validation
    (looks like leaked reasoning, a safety message, etc.) it's discarded
    entirely and the caller falls back to a static template, rather than
    risking a bad post going live.
    """
    for candidate in (discuss_and_write(context), generate_with_groq(context), generate_with_anthropic(context)):
        if not candidate:
            continue
        cleaned = clean_ai_text(candidate, allow_cashtag)
        if validate_post_text(cleaned):
            return cleaned
        print("⚠️ Discarding invalid AI output, trying next fallback...")
    return None


# ---------------------------------------------------------------------------
# Static reference content
# ---------------------------------------------------------------------------

GLOSSARY = {
    "Leverage": "Using a small amount of capital to control a larger position — it multiplies both gains and losses.",
    "Funding Rate": "A periodic payment between long and short traders in perpetual futures, keeping the contract price close to spot.",
    "Open Interest": "The total number of futures contracts still open — a signal of how much liquidity is actively in play.",
    "Support & Resistance": "Price levels where an asset tends to bounce (support) or struggle to break through (resistance).",
    "Candlestick": "A charting method showing the open, close, high, and low price over a set time period.",
    "Correction": "A temporary price decline, usually 10-20%, after a strong rally — before the broader trend resumes.",
    "Whales": "Wallets holding very large amounts of an asset. Their moves can noticeably shift the market.",
    "DCA (Dollar-Cost Averaging)": "Buying a fixed amount at regular intervals regardless of price, to smooth out volatility.",
    "Liquidity": "How easily an asset can be bought or sold without significantly moving its price.",
    "Liquidation": "The forced closing of a leveraged position once losses hit a threshold — the trader loses the margin used.",
    "Bull / Bear Market": "An extended period of sustained price increases (bull) or sustained declines (bear).",
    "ATH / ATL": "All-Time High or All-Time Low — the highest or lowest price an asset has ever reached.",
}

EVENTS = {
    "Word of the Day": "A simple daily quiz on the Binance app — a quick question about the market or platform, with a small reward for a correct answer.",
    "Red Packet": "A digital gift users can send each other in-app, containing a set amount of crypto.",
    "Megadrop": "A launch platform giving users a chance to earn tokens from new projects before they're officially listed, usually by locking BNB or completing tasks.",
    "Binance Alpha": "A section showcasing early-stage crypto projects before their full listing, giving users early access to promising tokens.",
    "Launchpool": "A program where locking coins like BNB or FDUSD earns you free tokens from a new project before it lists.",
    "Launchpad": "Binance's platform for launching new projects (IEOs), letting users buy tokens at a very early stage.",
    "HODLer Airdrops": "Free token distributions to users holding BNB in eligible products during a specific snapshot period.",
}


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def get_market_data(symbol: str) -> dict:
    pair = f"{symbol}USDT"

    ticker_resp = requests.get(SPOT_TICKER_URL, params={"symbol": pair}, timeout=10)
    ticker_resp.raise_for_status()
    ticker = ticker_resp.json()

    if "lastPrice" not in ticker:
        raise RuntimeError(f"Unexpected spot ticker response: {ticker}")

    data = {
        "symbol": symbol,
        "price": float(ticker["lastPrice"]),
        "change_pct": float(ticker["priceChangePercent"]),
        "funding_rate": None,
        "open_interest": None,
    }

    try:
        funding = requests.get(FAPI_FUNDING_URL, params={"symbol": pair}, timeout=10).json()
        data["funding_rate"] = float(funding["lastFundingRate"]) * 100
    except Exception as e:
        print(f"⚠️ Funding rate unavailable ({e}), skipping.")

    try:
        oi = requests.get(FAPI_OI_URL, params={"symbol": pair}, timeout=10).json()
        data["open_interest"] = float(oi["openInterest"])
    except Exception as e:
        print(f"⚠️ Open interest unavailable ({e}), skipping.")

    return data


def get_top_movers(limit: int = 5):
    resp = requests.get(SPOT_TICKER_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected ticker-all response: {data}")

    usdt = [
        d for d in data
        if isinstance(d, dict)
        and d.get("symbol", "").endswith("USDT")
        and float(d.get("quoteVolume", 0)) > 500_000
    ]

    gainers = sorted(usdt, key=lambda x: float(x["priceChangePercent"]), reverse=True)[:limit]
    losers = sorted(usdt, key=lambda x: float(x["priceChangePercent"]))[:limit]
    by_volume = sorted(usdt, key=lambda x: float(x["quoteVolume"]), reverse=True)[:limit]
    return gainers, losers, by_volume


def get_news(limit: int = 4) -> list:
    try:
        resp = requests.get(NEWS_URL, params={"lang": "EN"}, timeout=10)
        resp.raise_for_status()
        articles = resp.json().get("Data", [])
        articles = sorted(articles, key=lambda a: a.get("published_on", 0), reverse=True)
        return [
            {"title": a["title"].strip(), "source": a.get("source_info", {}).get("name") or a.get("source", "")}
            for a in articles[:limit]
            if a.get("title")
        ]
    except Exception as e:
        print(f"⚠️ News fetch failed ({e}), skipping.")
        return []


def get_rss_news(source_name: str, url: str, limit: int = 3) -> list:
    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = root.findall(".//item")[:limit]
        return [
            {"title": item.findtext("title", "").strip(), "source": source_name}
            for item in items
            if item.findtext("title")
        ]
    except Exception as e:
        print(f"⚠️ {source_name} RSS unavailable ({e}), skipping.")
        return []


def get_all_rss_news() -> list:
    articles = []
    for name, url in RSS_SOURCES.items():
        articles += get_rss_news(name, url)
    return articles


def get_macro_news() -> list:
    articles = []
    for name, url in MACRO_RSS_SOURCES.items():
        articles += get_rss_news(name, url, limit=6)
    return articles


def get_announcements(catalog_id: int, limit: int = 4) -> list:
    try:
        resp = requests.get(
            BAPI_ANNOUNCE_URL,
            params={"type": 1, "catalogId": catalog_id, "pageNo": 1, "pageSize": limit},
            headers=REQUEST_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json().get("data", {})

        catalogs = payload.get("catalogs", [])
        articles = catalogs[0].get("articles", []) if catalogs else payload.get("articles", [])

        return [
            {"title": a["title"].strip(), "code": a.get("code", "")}
            for a in articles[:limit]
            if a.get("title")
        ]
    except Exception as e:
        print(f"⚠️ Binance announcements unavailable ({e}), skipping.")
        return []


# ---------------------------------------------------------------------------
# Market update templates — hook-first, short paragraphs, closing question
# ---------------------------------------------------------------------------

def template_price_funding(d: dict) -> str:
    direction = "longs are paying shorts" if d["funding_rate"] > 0 else "shorts are paying longs"
    return (
        f"{d['symbol']} moved {abs(d['change_pct']):.2f}% in the last 24 hours — "
        f"but the funding rate is telling a different story than the price chart.\n\n"
        f"Price: ${d['price']:,.2f} ({d['change_pct']:+.2f}%)\n"
        f"Funding rate: {d['funding_rate']:.4f}% → {direction}\n"
        f"Open interest: {d['open_interest']:,.0f} contracts\n\n"
        f"Funding flips like this often show up right before short-term reversals.\n\n"
        f"Not financial advice. Where do you see {d['symbol']} going from here?"
    )


def template_technical(d: dict) -> str:
    support = d["price"] * 0.97
    resistance = d["price"] * 1.03
    return (
        f"{d['symbol']} is sitting right at a level that usually decides the next move.\n\n"
        f"Current price: ${d['price']:,.2f}\n"
        f"Nearby support: ~${support:,.2f}\n"
        f"Nearby resistance: ~${resistance:,.2f}\n\n"
        f"Hold above support and the trend likely continues. Lose it, and a deeper pullback opens up.\n\n"
        f"Not financial advice, just structure. Continuation or correction?"
    )


def template_general(d: dict) -> str:
    mood = "cautious optimism" if d["change_pct"] > 0 else "quiet nerves"
    return (
        f"Something shifted in {d['symbol']} sentiment today.\n\n"
        f"24h change: {d['change_pct']:+.2f}%\n"
        f"Market mood right now: {mood}\n\n"
        f"Markets tend to reward patience over panic — history keeps proving that one out.\n\n"
        f"Educational content only. Holding, or watching from the sidelines?"
    )


TEMPLATES_NEEDS_FUNDING = [template_price_funding]
TEMPLATES_SPOT_ONLY = [template_technical, template_general]


def template_top_movers(kind: str, movers: list) -> str:
    headers = {
        "gainers": "The biggest movers of the last 24 hours — starting with the winners:",
        "losers": "The biggest movers of the last 24 hours — starting with the pain:",
        "volume": "Here's where the real trading volume went in the last 24 hours:",
    }
    lines = [headers[kind]]
    for i, t in enumerate(movers, 1):
        sym = t["symbol"].replace("USDT", "")
        if kind == "volume":
            vol_m = float(t["quoteVolume"]) / 1_000_000
            lines.append(f"{i}. {sym}: ${vol_m:,.1f}M")
        else:
            lines.append(f"{i}. {sym}: {float(t['priceChangePercent']):+.2f}%")
    lines.append("")
    lines.append("Live data from Binance. Not financial advice — which one surprises you?")
    return "\n".join(lines)


def sarcastic_pump_1(d: dict) -> str:
    return (
        f"Funny how everyone becomes a \"long-term investor\" the second {d['symbol']} turns green.\n\n"
        f"Up {d['change_pct']:.2f}% today, and suddenly the group chats are full of technical analysts again.\n\n"
        f"Selective memory is undefeated.\n\n"
        f"Enjoy the move — just don't forget to take profit sometimes."
    )


def sarcastic_pump_2(d: dict) -> str:
    return (
        f"${d['price']:,.0f} on {d['symbol']} and the rocket emojis are back in full force.\n\n"
        f"Yesterday: \"I'll sell if it drops again.\"\n"
        f"Today: \"Holding to the moon.\"\n\n"
        f"Nothing changes a trader's conviction like one green candle.\n\n"
        f"Enjoy it, but a plan still beats an emotion."
    )


def sarcastic_dump_1(d: dict) -> str:
    return (
        f"Notice how quiet the group chats get when {d['symbol']} drops {abs(d['change_pct']):.2f}%?\n\n"
        f"Yesterday everyone was a market analyst. Today: silence.\n\n"
        f"Corrections are part of the game, not the end of it.\n\n"
        f"Who's still here?"
    )


def sarcastic_dump_2(d: dict) -> str:
    return (
        f"{d['symbol']} dips a bit and the market instantly splits into two types of people:\n\n"
        f"1. \"This is just a healthy correction.\"\n"
        f"2. *closes the app for a week*\n\n"
        f"For entertainment only — trading carries real risk. Which one are you today?"
    )


SARCASTIC_PUMP = [sarcastic_pump_1, sarcastic_pump_2]
SARCASTIC_DUMP = [sarcastic_dump_1, sarcastic_dump_2]


def build_news_post(articles: list) -> str:
    lines = ["The headlines actually moving crypto right now:"]
    for i, a in enumerate(articles, 1):
        src = f" — {a['source']}" if a["source"] else ""
        lines.append(f"{i}. {a['title']}{src}")
    lines.append("")
    lines.append("Which of these matters for price, and which is just noise? Curious what you think.")
    return "\n".join(lines)


def template_binance_news(articles: list, kind: str) -> str:
    header = "New listing alert on Binance:" if kind == "listing" else "Delisting notice on Binance:"
    lines = [header]
    for a in articles[:3]:
        lines.append(f"• {a['title']}")
    lines.append("")
    lines.append("Full details are on the official Announcements page in the app.")
    lines.append("Not financial advice.")
    return "\n".join(lines)


def template_glossary() -> str:
    term, explanation = random.choice(list(GLOSSARY.items()))
    return (
        f"Most traders skip this term, then wonder why the chart doesn't make sense.\n\n"
        f"{term}: {explanation}\n\n"
        f"Simple concepts, real trading edge. What term should we break down next?"
    )


def template_event() -> str:
    name, explanation = random.choice(list(EVENTS.items()))
    return (
        f"Most users scroll right past {name} without knowing what it actually does.\n\n"
        f"{explanation}\n\n"
        f"Check the Rewards Hub in the app so you don't miss the next one."
    )


# ---------------------------------------------------------------------------
# Chart image + image posting via Binance's official square-post skill
# ---------------------------------------------------------------------------

SQUARE_POST_SKILL_SCRIPT = "skill-src/skills/binance/square-post/scripts/post-image.mjs"
CHART_PATH = "chart.png"
KLINES_URL = "https://data-api.binance.vision/api/v3/klines"


def generate_price_chart(symbol: str) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        resp = requests.get(
            KLINES_URL,
            params={"symbol": f"{symbol}USDT", "interval": "1h", "limit": 24},
            timeout=15,
        )
        resp.raise_for_status()
        klines = resp.json()
        closes = [float(k[4]) for k in klines]
        if len(closes) < 2:
            return False

        color = "#0ECB81" if closes[-1] >= closes[0] else "#F6465D"
        fig, ax = plt.subplots(figsize=(6, 3.2), dpi=150)
        ax.plot(range(len(closes)), closes, color=color, linewidth=2.2)
        ax.fill_between(range(len(closes)), closes, min(closes), color=color, alpha=0.08)
        ax.set_title(f"{symbol}/USDT — Last 24h", fontsize=13, color="#EAECEF", pad=12)
        ax.set_facecolor("#181A20")
        fig.patch.set_facecolor("#181A20")
        ax.tick_params(colors="#848E9C", labelsize=8)
        ax.set_xticks([])
        for spine in ax.spines.values():
            spine.set_color("#2B3139")
        ax.grid(axis="y", color="#2B3139", linewidth=0.5)
        fig.tight_layout()
        fig.savefig(CHART_PATH, facecolor=fig.get_facecolor())
        plt.close(fig)
        return True
    except Exception as e:
        print(f"⚠️ Chart generation failed ({e}), skipping image.")
        return False


def post_to_square_with_image(text: str, image_path: str) -> bool:
    if not os.path.exists(SQUARE_POST_SKILL_SCRIPT):
        print("⚠️ Official post-image script not found, skipping image.")
        return False
    try:
        env = os.environ.copy()
        env["BINANCE_SQUARE_OPENAPI_KEY"] = API_KEY or ""
        result = subprocess.run(
            ["node", SQUARE_POST_SKILL_SCRIPT, "--text", text, "--images", image_path],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"⚠️ Image post script failed: {result.stderr}")
            return False
        return "Success" in result.stdout
    except Exception as e:
        print(f"⚠️ Image post script errored ({e}).")
        return False


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------

def post_to_square(text: str) -> dict:
    if not API_KEY:
        raise RuntimeError("SQUARE_OPENAPI_KEY environment variable is not set.")

    headers = {
        "X-Square-OpenAPI-Key": API_KEY,
        "Content-Type": "application/json",
        "clienttype": "binanceSkill",
    }
    payload = {"bodyTextOnly": text}

    resp = requests.post(SQUARE_POST_URL, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def choose_category() -> str:
    categories = list(CATEGORY_WEIGHTS.keys())
    weights = list(CATEGORY_WEIGHTS.values())
    return random.choices(categories, weights=weights, k=1)[0]


def main():
    category = choose_category()
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Category selected: {category}")
    text = None

    if category == "binance_news":
        kind = random.choice(["listing", "delisting"])
        catalog_id = CATALOG_NEW_LISTING if kind == "listing" else CATALOG_DELISTING
        articles = get_announcements(catalog_id)
        if articles:
            label = "New listing announcements" if kind == "listing" else "Delisting announcements"
            context = f"Category: Binance official {label}\nHeadlines:\n" + "\n".join(f"- {a['title']}" for a in articles)
            text = generate_with_ai(context, allow_cashtag=False) or template_binance_news(articles, kind)
        else:
            print("No Binance announcements available, falling back to general news.")
            category = "general_news"

    if category == "general_news":
        articles = get_news() + get_all_rss_news()
        random.shuffle(articles)
        articles = articles[:4]
        if articles:
            context = "Category: general crypto news roundup\nHeadlines:\n" + "\n".join(
                f"- {a['title']} ({a['source']})" for a in articles
            )
            text = generate_with_ai(context, allow_cashtag=False) or build_news_post(articles)
        else:
            print("No general news available, falling back to analysis.")
            category = "analysis"

    if category == "macro_news":
        articles = get_macro_news()
        if articles:
            random.shuffle(articles)
            articles = articles[:4]
            context = (
                "Category: macro-economic news affecting crypto/markets broadly "
                "(Fed policy, CPI/inflation, jobs data, GDP, geopolitics, corporate "
                "earnings -- NOT crypto-native news)\nHeadlines:\n"
                + "\n".join(f"- {a['title']} ({a['source']})" for a in articles)
            )
            text = generate_with_ai(context, allow_cashtag=False) or build_news_post(articles)
        else:
            print("No macro news available, falling back to general news.")
            category = "general_news"
            articles = get_news() + get_all_rss_news()
            random.shuffle(articles)
            articles = articles[:4]
            if articles:
                context = "Category: general crypto news roundup\nHeadlines:\n" + "\n".join(
                    f"- {a['title']} ({a['source']})" for a in articles
                )
                text = generate_with_ai(context, allow_cashtag=False) or build_news_post(articles)
            else:
                category = "analysis"

    if category == "analysis":
        sub = random.choice(["symbol", "movers"])
        if sub == "movers":
            try:
                gainers, losers, by_volume = get_top_movers()
                kind = random.choice(["gainers", "losers", "volume"])
                movers = {"gainers": gainers, "losers": losers, "volume": by_volume}[kind]
            except Exception as e:
                print(f"⚠️ Top movers unavailable ({e}), falling back to symbol analysis.")
                movers = []
            if movers:
                label = {"gainers": "top gainers", "losers": "top losers", "volume": "top volume"}[kind]
                lines = []
                for t in movers:
                    sym = t["symbol"].replace("USDT", "")
                    if kind == "volume":
                        lines.append(f"- {sym}: ${float(t['quoteVolume'])/1_000_000:,.1f}M 24h volume")
                    else:
                        lines.append(f"- {sym}: {float(t['priceChangePercent']):+.2f}% 24h")
                context = f"Category: market analysis ({label}, last 24h)\n" + "\n".join(lines)
                text = generate_with_ai(context, allow_cashtag=False) or template_top_movers(kind, movers)
        if text is None:
            symbol = random.choice(SYMBOLS)
            print(f"Fetching data for {symbol}...")
            data = get_market_data(symbol)
            context_lines = [
                "Category: market analysis (single asset)",
                f"Symbol: {data['symbol']}",
                f"Price: ${data['price']:,.2f}",
                f"24h change: {data['change_pct']:+.2f}%",
            ]
            if data["funding_rate"] is not None:
                context_lines.append(f"Funding rate: {data['funding_rate']:.4f}%")
            if data["open_interest"] is not None:
                context_lines.append(f"Open interest: {data['open_interest']:,.0f} contracts")
            context = "\n".join(context_lines)
            ai_text = generate_with_ai(context)
            if ai_text:
                text = ai_text
            else:
                available_templates = list(TEMPLATES_SPOT_ONLY)
                if data["funding_rate"] is not None and data["open_interest"] is not None:
                    available_templates += TEMPLATES_NEEDS_FUNDING
                text = random.choice(available_templates)(data)

    if category == "education":
        term, explanation = random.choice(list(GLOSSARY.items()))
        context = f"Category: trading education\nTerm: {term}\nDefinition: {explanation}"
        text = generate_with_ai(context, allow_cashtag=False) or (
            f"Most traders skip this term, then wonder why the chart doesn't make sense.\n\n"
            f"{term}: {explanation}\n\n"
            f"Simple concepts, real trading edge. What term should we break down next?"
        )

    if category == "sarcastic":
        symbol = random.choice(SYMBOLS)
        print(f"Fetching data for {symbol}...")
        data = get_market_data(symbol)
        mood = "pumping" if data["change_pct"] > 0 else "dumping"
        context = (
            f"Category: sarcastic/meme market commentary\n"
            f"Symbol: {data['symbol']}\n"
            f"24h change: {data['change_pct']:+.2f}%\n"
            f"Mood: {mood}\n"
            f"Tone: witty, self-aware, poking fun at trader psychology (not mean-spirited)."
        )
        ai_text = generate_with_ai(context)
        if ai_text:
            text = ai_text
        else:
            pool = SARCASTIC_PUMP if data["change_pct"] > 0 else SARCASTIC_DUMP
            text = random.choice(pool)(data)

    if category == "events":
        name, explanation = random.choice(list(EVENTS.items()))
        context = f"Category: Binance platform event explainer\nEvent name: {name}\nDescription: {explanation}"
        text = generate_with_ai(context, allow_cashtag=False) or (
            f"Most users scroll right past {name} without knowing what it actually does.\n\n"
            f"{explanation}\n\n"
            f"Check the Rewards Hub in the app so you don't miss the next one."
        )

    # Final safety net -- even a static template is checked (cheap, and
    # guarantees nothing bypasses validation regardless of code path).
    if text is None or not validate_post_text(text):
        print("❌ No valid content could be generated for this run.")
        sys.exit(1)

    print("---- Generated post ----")
    print(text)
    print("-------------------------")

    posted_with_image = False
    if category == "analysis" and "symbol" in locals().get("data", {}):
        if generate_price_chart(data["symbol"]):
            posted_with_image = post_to_square_with_image(text, CHART_PATH)

    if posted_with_image:
        print("✅ Posted successfully with image.")
        return

    result = post_to_square(text)

    if result.get("code") == "000000":
        post_id = result.get("data", {}).get("id", "unknown")
        print(f"✅ Posted successfully. ID: {post_id}")
        print(f"🔗 https://www.binance.com/square/post/{post_id}")
    else:
        print(f"❌ Post failed: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()
