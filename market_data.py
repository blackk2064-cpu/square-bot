from http_utils import request_with_retry

SPOT_TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"
FAPI_FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
FAPI_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SquareBot/1.0)"}


def get_spot_snapshot(symbols):
    resp = request_with_retry("GET", SPOT_TICKER_URL, headers=HEADERS)
    data = resp.json()
    by_symbol = {row["symbol"]: row for row in data}
    result = {}
    for sym in symbols:
        pair = f"{sym}USDT"
        row = by_symbol.get(pair)
        if not row:
            continue
        result[sym] = {
            "price": float(row["lastPrice"]),
            "change_pct": float(row["priceChangePercent"]),
            "volume": float(row["volume"]),
            "quote_volume": float(row["quoteVolume"]),
        }
    return result


def get_futures_snapshot(symbols):
    result = {}
    for sym in symbols:
        pair = f"{sym}USDT"
        entry = {}
        try:
            resp = request_with_retry("GET", FAPI_FUNDING_URL, params={"symbol": pair}, headers=HEADERS)
            row = resp.json()
            entry["funding_rate"] = float(row.get("lastFundingRate", 0))
        except Exception:
            entry["funding_rate"] = None
        try:
            resp = request_with_retry("GET", FAPI_OI_URL, params={"symbol": pair}, headers=HEADERS)
            row = resp.json()
            entry["open_interest"] = float(row.get("openInterest", 0))
        except Exception:
            entry["open_interest"] = None
        result[sym] = entry
    return result


def get_top_movers(exclude_symbols=None, quote="USDT", min_quote_volume=5_000_000, limit=3):
    """
    يرجّع أعلى العملات حركة (% تغيّر مطلق) خلال 24 ساعة من بين كل أزواج
    USDT، باستبعاد الرموز اللي أصلًا في القايمة الثابتة، وبشرط حد أدنى من
    السيولة (quote_volume) عشان نتجنب عملات صغيرة جدًا أو وهمية الحركة.
    بيستخدم نفس استدعاء SPOT_TICKER_URL اللي get_spot_snapshot بتستخدمه،
    فمفيش تكلفة إضافية على الـ API غير طلب واحد.
    """
    exclude_symbols = set(exclude_symbols or [])
    resp = request_with_retry("GET", SPOT_TICKER_URL, headers=HEADERS)
    data = resp.json()

    candidates = []
    for row in data:
        pair = row["symbol"]
        if not pair.endswith(quote):
            continue
        base = pair[: -len(quote)]
        if base in exclude_symbols:
            continue
        try:
            change_pct = float(row["priceChangePercent"])
            quote_volume = float(row["quoteVolume"])
        except (KeyError, ValueError):
            continue
        if quote_volume < min_quote_volume:
            continue
        candidates.append((base, change_pct, quote_volume))

    candidates.sort(key=lambda x: abs(x[1]), reverse=True)
    return [c[0] for c in candidates[:limit]]


def build_market_snapshot(symbols, include_top_movers=0):
    """
    symbols: القايمة الثابتة من config.yaml (BTC, ETH, SOL, BNB...).
    include_top_movers: عدد العملات الإضافية (غير الثابتة) اللي هتتضاف
    ديناميكيًا كل تشغيلة بناءً على أعلى % تغيّر خلال 24 ساعة. 0 يعني
    نفس السلوك القديم (الرموز الثابتة بس).
    """
    all_symbols = list(symbols)
    if include_top_movers > 0:
        movers = get_top_movers(exclude_symbols=symbols, limit=include_top_movers)
        all_symbols = all_symbols + movers

    spot = get_spot_snapshot(all_symbols)
    futures = get_futures_snapshot(all_symbols)
    snapshot = {}
    for sym in all_symbols:
        snapshot[sym] = {**spot.get(sym, {}), **futures.get(sym, {})}
    return snapshot
