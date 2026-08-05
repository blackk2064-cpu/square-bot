#!/usr/bin/env python3
"""
Binance Square Auto-Poster Bot
================================
Fetches live market data + crypto news from public APIs and posts an
auto-generated Arabic update to Binance Square using the official
Square OpenAPI (X-Square-OpenAPI-Key).

Each run randomly picks ONE post type:
  - "market"    (55%): price / technical / funding-rate style updates
  - "sarcastic" (25%): witty/sarcastic commentary on the day's move
  - "news"      (20%): roundup of top market-moving headlines

Run once per invocation — scheduled hourly via GitHub Actions.

Required environment variable:
    SQUARE_OPENAPI_KEY   -> your Binance Square OpenAPI key (Creator Center)
"""

import os
import random
import sys
import time
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

SYMBOLS = ["BTC", "ETH", "SOL", "BNB"]

# Relative weights for post type selection per run.
CATEGORY_WEIGHTS = {"market": 55, "sarcastic": 25, "news": 20}

API_KEY = os.environ.get("SQUARE_OPENAPI_KEY")


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def get_market_data(symbol: str) -> dict:
    """Pull 24h price change (required) and funding/OI (best-effort) for a symbol."""
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


def get_news(limit: int = 4) -> list:
    """Fetch top recent crypto headlines. Returns [] on any failure."""
    try:
        resp = requests.get(NEWS_URL, params={"lang": "EN"}, timeout=10)
        resp.raise_for_status()
        articles = resp.json().get("Data", [])
        # Sort newest first and keep only the fields we need.
        articles = sorted(articles, key=lambda a: a.get("published_on", 0), reverse=True)
        return [
            {"title": a["title"].strip(), "source": a.get("source_info", {}).get("name") or a.get("source", "")}
            for a in articles[:limit]
            if a.get("title")
        ]
    except Exception as e:
        print(f"⚠️ News fetch failed ({e}), skipping news category.")
        return []


# ---------------------------------------------------------------------------
# Market update templates (Arabic)
# ---------------------------------------------------------------------------

def template_price_funding(d: dict) -> str:
    """Requires funding_rate and open_interest to be present (not None)."""
    direction = "إيجابي → الطويلون يدفعون" if d["funding_rate"] > 0 else "سلبي → القصيرون يدفعون"
    trend = "صاعد 📈" if d["change_pct"] > 0 else "هابط 📉"
    return (
        f"🔥 تحديث {d['symbol']} (بيانات باينانس):\n"
        f"• السعر الحالي: ${d['price']:,.2f}\n"
        f"• التغير 24 ساعة: {d['change_pct']:.2f}% {trend}\n"
        f"• معدل التمويل: {d['funding_rate']:.4f}% → {direction}\n"
        f"• الفائدة المفتوحة: {d['open_interest']:,.0f} عقد\n\n"
        f"📊 السوق يتحرك بسرعة، تابعوا معنا التحديثات.\n"
        f"⚠️ ليست نصيحة استثمارية — التداول فيه مخاطرة.\n"
        f"#{d['symbol']} #كريبتو #بايننس #تداول"
    )


def template_technical(d: dict) -> str:
    support = d["price"] * 0.97
    resistance = d["price"] * 1.03
    return (
        f"📊 قراءة فنية سريعة على ${d['symbol']}:\n"
        f"السعر الحالي حول ${d['price']:,.2f}\n"
        f"منطقة الدعم القريبة: ~${support:,.2f}\n"
        f"منطقة المقاومة القريبة: ~${resistance:,.2f}\n\n"
        f"الاحتفاظ فوق الدعم = استمرار الاتجاه الحالي\n"
        f"كسر الدعم = احتمال تصحيح أعمق\n\n"
        f"👇 رأيك: صعود أم تصحيح؟\n"
        f"⚠️ للتوضيح فقط، وليست نصيحة استثمارية.\n"
        f"#{d['symbol']} #تحليل_فني #كريبتو"
    )


def template_general(d: dict) -> str:
    mood = "تفاؤل واضح 🟢" if d["change_pct"] > 0 else "حذر وترقب 🟡"
    return (
        f"🚨 نبض السوق الآن على ${d['symbol']}:\n"
        f"مزاج المتداولين: {mood}\n"
        f"التغير اليومي: {d['change_pct']:.2f}%\n\n"
        f"السوق دايمًا بيكافئ الصبور مش المستعجل.\n"
        f"تابعونا لتحديثات مستمرة عن حركة السوق.\n\n"
        f"⚠️ محتوى تعليمي فقط، استثمر بما يمكنك تحمل خسارته.\n"
        f"#كريبتو #بايننس #سوق_الكريبتو"
    )


TEMPLATES_NEEDS_FUNDING = [template_price_funding]
TEMPLATES_SPOT_ONLY = [template_technical, template_general]


# ---------------------------------------------------------------------------
# Sarcastic / humorous templates (Arabic) — picked by current mood (pump/dump)
# ---------------------------------------------------------------------------

def sarcastic_pump_1(d: dict) -> str:
    return (
        f"😂 {d['symbol']} طالع {d['change_pct']:.2f}% ودلوقتي فجأة كل اللي كانوا\n"
        f"بيقولوا \"الكريبتو نصب\" بقوا محللين فنيين ومستثمرين للأجل الطويل 🎩\n\n"
        f"الذاكرة السمكية أسطورة بجد 🐟\n\n"
        f"⚠️ استمتعوا بس متنسوش تاخدوا أرباحكم أحيانًا 😅\n"
        f"#{d['symbol']} #كريبتو #كوميك_السوق"
    )


def sarcastic_pump_2(d: dict) -> str:
    return (
        f"🚀 ${d['price']:,.0f} على {d['symbol']}!\n\n"
        f"المجموعات دلوقتي بقت فيها إيموجي صاروخ أكتر من كلام 🚀🚀🚀\n"
        f"واللي كان \"هيبيع لو نزل تاني\" بقى \"هولد لحد القمر\" 🌕\n\n"
        f"يا رب سلامة القلوب 😂\n"
        f"⚠️ الفرحة حلوة بس الخطة أهم.\n"
        f"#{d['symbol']} #كريبتو"
    )


def sarcastic_dump_1(d: dict) -> str:
    return (
        f"😅 {d['symbol']} نازل {abs(d['change_pct']):.2f}% والمجموعات فجأة\n"
        f"بقت هادية أوي... حتى البوتات مبتردش 🤖\n\n"
        f"فاكرين لما كان طالع وكل واحد \"محلل\"؟ وحشتونا 🥲\n\n"
        f"⚠️ التصحيحات جزء من اللعبة، خليكوا هادئين.\n"
        f"#{d['symbol']} #كريبتو #السوق_الهابط"
    )


def sarcastic_dump_2(d: dict) -> str:
    return (
        f"📉 {d['symbol']} نازل شوية، وبقى فيه صنفين بس في السوق دلوقتي:\n"
        f"1) اللي بيقول \"ده تصحيح صحي\" 🧘\n"
        f"2) اللي بيقفل التطبيق ويفتحه بعد أسبوع 🙈\n\n"
        f"انتوا مين فيهم؟ 😂\n"
        f"⚠️ محتوى ترفيهي، والتداول فيه مخاطرة حقيقية.\n"
        f"#{d['symbol']} #كريبتو"
    )


SARCASTIC_PUMP = [sarcastic_pump_1, sarcastic_pump_2]
SARCASTIC_DUMP = [sarcastic_dump_1, sarcastic_dump_2]


# ---------------------------------------------------------------------------
# News roundup
# ---------------------------------------------------------------------------

def build_news_post(articles: list) -> str:
    lines = ["📰 أهم العناوين المؤثرة على السوق الآن:"]
    for i, a in enumerate(articles, 1):
        src = f" — {a['source']}" if a["source"] else ""
        lines.append(f"{i}. {a['title']}{src}")
    lines.append("")
    lines.append("👀 تابعونا لمزيد من تحديثات الأخبار لحظة بلحظة.")
    lines.append("⚠️ أخبار فقط، وليست نصيحة استثمارية.")
    lines.append("#أخبار_الكريبتو #بايننس #سوق_العملات_الرقمية")
    return "\n".join(lines)


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

    if category == "news":
        articles = get_news()
        if articles:
            text = build_news_post(articles)
        else:
            print("No news available, falling back to market update.")
            category = "market"

    if category in ("market", "sarcastic"):
        symbol = random.choice(SYMBOLS)
        print(f"Fetching data for {symbol}...")
        data = get_market_data(symbol)

        if category == "sarcastic":
            pool = SARCASTIC_PUMP if data["change_pct"] > 0 else SARCASTIC_DUMP
            text = random.choice(pool)(data)
        else:
            available_templates = list(TEMPLATES_SPOT_ONLY)
            if data["funding_rate"] is not None and data["open_interest"] is not None:
                available_templates += TEMPLATES_NEEDS_FUNDING
            text = random.choice(available_templates)(data)

    print("---- Generated post ----")
    print(text)
    print("-------------------------")

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
