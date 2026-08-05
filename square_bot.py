#!/usr/bin/env python3
"""
Binance Square Auto-Poster Bot
================================
Fetches live market data from Binance's public REST API (no auth needed)
and posts an auto-generated Arabic market update to Binance Square using
the official Square OpenAPI (X-Square-OpenAPI-Key).

Run once per invocation — schedule it externally (cron / GitHub Actions)
to run hourly.

Required environment variable:
    SQUARE_OPENAPI_KEY   -> your Binance Square OpenAPI key (Creator Center)

Docs referenced:
    Square post endpoint: POST /bapi/composite/v1/public/pgc/openApi/content/add
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
SPOT_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
FAPI_FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
FAPI_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"

SYMBOLS = ["BTC", "ETH", "SOL", "BNB"]

API_KEY = os.environ.get("SQUARE_OPENAPI_KEY")


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------

def get_market_data(symbol: str) -> dict:
    """Pull 24h price change, funding rate, and open interest for a symbol."""
    pair = f"{symbol}USDT"

    ticker = requests.get(SPOT_TICKER_URL, params={"symbol": pair}, timeout=10).json()
    funding = requests.get(FAPI_FUNDING_URL, params={"symbol": pair}, timeout=10).json()
    oi = requests.get(FAPI_OI_URL, params={"symbol": pair}, timeout=10).json()

    return {
        "symbol": symbol,
        "price": float(ticker["lastPrice"]),
        "change_pct": float(ticker["priceChangePercent"]),
        "funding_rate": float(funding["lastFundingRate"]) * 100,
        "open_interest": float(oi["openInterest"]),
    }


# ---------------------------------------------------------------------------
# Post templates (Arabic) — mirrors the account's existing style
# ---------------------------------------------------------------------------

def template_price_funding(d: dict) -> str:
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


TEMPLATES = [template_price_funding, template_technical, template_general]


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

def main():
    symbol = random.choice(SYMBOLS)
    template_fn = random.choice(TEMPLATES)

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Fetching data for {symbol}...")
    data = get_market_data(symbol)

    text = template_fn(data)
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
