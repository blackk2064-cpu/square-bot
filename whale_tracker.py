import os
import time

from http_utils import request_with_retry

ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY")
ETHERSCAN_API_URL = "https://api.etherscan.io/api"

# Small, fixed watchlist of well-known PUBLIC addresses (exchange cold
# wallets / publicly labeled funds). These are all addresses that are
# already publicly labeled on block explorers — nothing private or
# deanonymizing here, same as any public "whale alert" style account.
WATCHLIST = {
    "Binance 14": "0x28c6c06298d514db089934071355e5743bf21d60",
    "Binance 8": "0xf977814e90da44bfa03b6295a0616a897441acec",
}

MIN_USD_MOVE_TO_REPORT = 5_000_000


def _get_eth_balance(address):
    if not ETHERSCAN_API_KEY:
        return None
    params = {
        "module": "account",
        "action": "balance",
        "address": address,
        "tag": "latest",
        "apikey": ETHERSCAN_API_KEY,
    }
    try:
        resp = request_with_retry("GET", ETHERSCAN_API_URL, params=params)
        data = resp.json()
        if data.get("status") != "1":
            return None
        return int(data["result"]) / 1e18
    except Exception as e:
        print(f"⚠️ Whale balance fetch failed for {address}: {e}")
        return None


def get_watchlist_snapshot():
    """
    Returns {label: balance_eth} for the public watchlist. This is a plain
    balance read, not a transaction feed — deliberately conservative to
    avoid over-interpreting single transfers as trading signals.
    """
    snapshot = {}
    for label, address in WATCHLIST.items():
        bal = _get_eth_balance(address)
        if bal is not None:
            snapshot[label] = bal
    return snapshot


def detect_significant_moves(previous_snapshot, current_snapshot, eth_price_usd):
    """
    Compares two balance snapshots (e.g. this run vs the last recorded run)
    and returns a list of plain-language, source-labeled move descriptions
    for balances that changed by more than MIN_USD_MOVE_TO_REPORT.
    """
    moves = []
    if not previous_snapshot or not eth_price_usd:
        return moves
    for label, current_bal in current_snapshot.items():
        prev_bal = previous_snapshot.get(label)
        if prev_bal is None:
            continue
        delta_eth = current_bal - prev_bal
        delta_usd = delta_eth * eth_price_usd
        if abs(delta_usd) >= MIN_USD_MOVE_TO_REPORT:
            direction = "inflow to" if delta_eth > 0 else "outflow from"
            moves.append(
                f"Public on-chain data: {direction} labeled wallet '{label}' "
                f"of about {abs(delta_eth):,.0f} ETH (~${abs(delta_usd):,.0f}), "
                f"per Etherscan's public label for this address."
            )
    return moves
