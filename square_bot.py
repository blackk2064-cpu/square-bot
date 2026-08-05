#!/usr/bin/env python3
"""
Binance Square Auto-Poster Bot
================================
Fetches live market data / news / announcements from public APIs and posts
an auto-generated Arabic update to Binance Square using the official
Square OpenAPI (X-Square-OpenAPI-Key).

Each run randomly picks ONE post type, roughly matching:
  - 40%  news     (24% Binance official listing/delisting, 16% general crypto news)
  - 20%  analysis (price/technical/funding OR top gainers-losers-volume)
  - 15%  education (trading term glossary)
  - 15%  memes/sarcastic
  - 10%  Binance events explainer (Launchpool, Megadrop, Alpha, etc.)

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

# NOTE: this is an *unofficial* internal endpoint used by binance.com's own
# website to render its announcements page. It is not part of Binance's
# documented developer API, has no stability guarantee, and has been known
# to return 403 without warning. Treated as best-effort like funding data.
BAPI_ANNOUNCE_URL = "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
CATALOG_NEW_LISTING = 48
CATALOG_DELISTING = 161

SYMBOLS = ["BTC", "ETH", "SOL", "BNB"]

# Relative weights for post type selection per run (~ matches 40/20/15/15/10
# split, with "news" broken into Binance-official vs general crypto news).
CATEGORY_WEIGHTS = {
    "binance_news": 24,
    "general_news": 16,
    "analysis": 20,
    "education": 15,
    "sarcastic": 15,
    "events": 10,
}

API_KEY = os.environ.get("SQUARE_OPENAPI_KEY")
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SquareBot/1.0)"}


# ---------------------------------------------------------------------------
# Static reference content
# ---------------------------------------------------------------------------

GLOSSARY = {
    "الرافعة المالية (Leverage)": "استخدام مبلغ صغير من رأس المال للتحكم في مركز أكبر، بيضاعف الأرباح والخسائر مع بعض.",
    "معدل التمويل (Funding Rate)": "رسوم دورية بين المتداولين الطويلين والقصيرين في عقود الفيوتشرز الدائمة، بتحافظ على سعر العقد قريب من السعر الفوري.",
    "الفائدة المفتوحة (Open Interest)": "إجمالي عدد العقود المفتوحة (اللي لسه متقفلتش) في سوق المشتقات، بيعكس حجم السيولة النشطة.",
    "الدعم والمقاومة (Support/Resistance)": "مستويات سعرية بيميل السعر يرتد عندها لأعلى (دعم) أو لأسفل (مقاومة) بناءً على التاريخ السعري.",
    "الشمعة اليابانية (Candlestick)": "طريقة رسم بيانية بتوضح سعر الفتح والإغلاق وأعلى وأقل سعر خلال فترة زمنية معينة.",
    "التصحيح (Correction)": "انخفاض مؤقت في السعر بعد ارتفاع قوي، قبل ما يكمل الاتجاه الأساسي.",
    "الحيتان (Whales)": "محافظ ضخمة بتمتلك كميات كبيرة من عملة معينة، وتحركاتها ممكن تأثر على السعر بشكل ملحوظ.",
    "DCA (متوسط التكلفة الدولاري)": "استراتيجية شراء مبلغ ثابت بشكل دوري بغض النظر عن السعر، لتقليل تأثير التقلبات.",
    "السيولة (Liquidity)": "سهولة شراء أو بيع أصل من غير ما يأثر بشكل كبير على سعره.",
    "التصفية (Liquidation)": "إغلاق إجباري لمركز تداول بالرافعة المالية لما الخسائر توصل لحد معين، وبيخسر المتداول الهامش المستخدم.",
    "السوق الصاعد/الهابط (Bull/Bear Market)": "فترة طويلة من الارتفاع المستمر (صاعد) أو الانخفاض المستمر (هابط) في السوق.",
    "القمة/القاع (ATH/ATL)": "أعلى سعر أو أقل سعر وصلت له عملة في تاريخها.",
}

EVENTS = {
    "Word of the Day": "مسابقة يومية بسيطة على تطبيق باينانس، بتسأل سؤال قصير عن السوق أو المنصة، والإجابة الصحيحة بتديك فرصة في مكافأة صغيرة.",
    "Red Packet": "هدية رقمية يقدر المستخدمين يبعتوها لبعض جوه التطبيق، بتحتوي على عملات رقمية بقيمة معينة.",
    "Megadrop": "منصة إطلاق مشاريع جديدة بتدي المستخدمين فرصة يحصلوا على توكنات مشروع قبل إدراجه رسميًا، غالبًا عن طريق قفل BNB أو أداء مهام.",
    "Binance Alpha": "قسم بيعرض مشاريع كريبتو ناشئة قبل الإدراج الكامل على باينانس، بيدي وصول مبكر لتوكنات واعدة.",
    "Launchpool": "برنامج بيتيح قفل عملات زي BNB أو FDUSD عشان تكسب توكنات مشروع جديد مجانًا قبل إدراجه.",
    "Launchpad": "منصة باينانس لإطلاق مشاريع جديدة (IEO) بيقدر المستخدمين يشتروا فيها توكنات في مرحلة مبكرة جدًا.",
    "HODLer Airdrops": "توزيعات مجانية لتوكنات مشاريع جديدة على المستخدمين اللي عندهم BNB محتفظ بيه في فترة معينة.",
}


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


def get_top_movers(limit: int = 5):
    """Returns (gainers, losers, by_volume) lists of USDT-pair ticker dicts."""
    resp = requests.get(SPOT_TICKER_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected ticker-all response: {data}")

    usdt = [
        d for d in data
        if isinstance(d, dict)
        and d.get("symbol", "").endswith("USDT")
        and float(d.get("quoteVolume", 0)) > 500_000  # filter out illiquid noise
    ]

    gainers = sorted(usdt, key=lambda x: float(x["priceChangePercent"]), reverse=True)[:limit]
    losers = sorted(usdt, key=lambda x: float(x["priceChangePercent"]))[:limit]
    by_volume = sorted(usdt, key=lambda x: float(x["quoteVolume"]), reverse=True)[:limit]
    return gainers, losers, by_volume


def get_news(limit: int = 4) -> list:
    """Fetch top recent general crypto headlines. Returns [] on any failure."""
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


def get_announcements(catalog_id: int, limit: int = 4) -> list:
    """
    Best-effort fetch of Binance's own listing/delisting announcements via
    the internal endpoint their website uses. NOT an officially documented
    API — may return 403 or change shape at any time. Always returns []
    instead of raising, so the caller can fall back to another post type.
    """
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


def template_top_movers(kind: str, movers: list) -> str:
    headers = {
        "gainers": "🚀 الأعلى ارتفاعًا في آخر 24 ساعة:",
        "losers": "🔻 الأعلى انخفاضًا في آخر 24 ساعة:",
        "volume": "📊 الأعلى في حجم التداول (24 ساعة):",
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
    lines.append("⚠️ بيانات لحظية من باينانس، وليست نصيحة استثمارية.")
    lines.append("#كريبتو #بايننس #تداول")
    return "\n".join(lines)


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
# News / announcements / education / events builders
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


def template_binance_news(articles: list, kind: str) -> str:
    header = "📢 إعلانات إدراج جديدة على باينانس:" if kind == "listing" else "⚠️ إعلانات شطب على باينانس:"
    lines = [header]
    for a in articles[:3]:
        lines.append(f"• {a['title']}")
    lines.append("")
    lines.append("🔗 راجعوا التفاصيل الكاملة في صفحة الإعلانات الرسمية على التطبيق.")
    lines.append("⚠️ ليست نصيحة استثمارية.")
    lines.append("#باينانس #Binance #كريبتو")
    return "\n".join(lines)


def template_glossary() -> str:
    term, explanation = random.choice(list(GLOSSARY.items()))
    return (
        f"📚 مصطلح تداول اليوم: {term}\n\n"
        f"{explanation}\n\n"
        f"تابعونا لمزيد من المصطلحات المبسطة كل يوم.\n"
        f"#تعلم_التداول #كريبتو #بايننس"
    )


def template_event() -> str:
    name, explanation = random.choice(list(EVENTS.items()))
    return (
        f"🎁 إيه هو {name} على باينانس؟\n\n"
        f"{explanation}\n\n"
        f"تابعوا صفحة المكافآت (Rewards Hub) في التطبيق عشان متفوتوش الفرص الجديدة.\n"
        f"#بايننس #Binance"
    )


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
            text = template_binance_news(articles, kind)
        else:
            print("No Binance announcements available, falling back to general news.")
            category = "general_news"

    if category == "general_news":
        articles = get_news()
        if articles:
            text = build_news_post(articles)
        else:
            print("No general news available, falling back to analysis.")
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
                text = template_top_movers(kind, movers)
        if text is None:
            symbol = random.choice(SYMBOLS)
            print(f"Fetching data for {symbol}...")
            data = get_market_data(symbol)
            available_templates = list(TEMPLATES_SPOT_ONLY)
            if data["funding_rate"] is not None and data["open_interest"] is not None:
                available_templates += TEMPLATES_NEEDS_FUNDING
            text = random.choice(available_templates)(data)

    if category == "education":
        text = template_glossary()

    if category == "sarcastic":
        symbol = random.choice(SYMBOLS)
        print(f"Fetching data for {symbol}...")
        data = get_market_data(symbol)
        pool = SARCASTIC_PUMP if data["change_pct"] > 0 else SARCASTIC_DUMP
        text = random.choice(pool)(data)

    if category == "events":
        text = template_event()

    if text is None:
        print("❌ No content could be generated for this run.")
        sys.exit(1)

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
