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


def build_market_snapshot(symbols):
    spot = get_spot_snapshot(symbols)
    futures = get_futures_snapshot(symbols)
    snapshot = {}
    for sym in symbols:
        snapshot[sym] = {**spot.get(sym, {}), **futures.get(sym, {})}
    return snapshot
