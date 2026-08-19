import os
import sys
import random

from config_loader import load_config
from market_data import build_market_snapshot
from news_data import get_top_stories, get_macro_headlines
from content_pipeline import generate_post
from state_store import load_state, save_state, is_duplicate, in_cooldown, record_post
from hooks import pick_hook_style
from whale_tracker import get_watchlist_snapshot, detect_significant_moves

API_KEY = os.environ.get("SQUARE_OPENAPI_KEY")


def pick_category(weights_cfg):
    weights = {k: v for k, v in weights_cfg.items() if k not in ("min_weight", "max_weight")}
    categories = list(weights.keys())
    values = list(weights.values())
    return random.choices(categories, weights=values, k=1)[0]


def build_trusted_data_text(symbol, market_snapshot):
    data = market_snapshot.get(symbol)
    if not data:
        return f"No verified market data available for {symbol}."
    lines = [f"Symbol: {symbol}"]
    if "price" in data:
        lines.append(f"Price: {data['price']}")
    if "change_pct" in data:
        lines.append(f"24h change: {data['change_pct']}%")
    if "volume" in data:
        lines.append(f"24h volume: {data['volume']}")
    if data.get("funding_rate") is not None:
        lines.append(f"Funding rate: {data['funding_rate']}")
    if data.get("open_interest") is not None:
        lines.append(f"Open interest: {data['open_interest']}")
    return "\n".join(lines)


def build_news_untrusted_text(stories):
    lines = []
    for story in stories:
        sources = ", ".join(story["sources"])
        lines.append(f"- {story['title']} (sources: {sources})")
    return "\n".join(lines)


def run():
    cfg = load_config()
    posting_cfg = cfg["posting"]
    symbols = cfg["symbols"]

    if not API_KEY:
        print("SQUARE_OPENAPI_KEY missing, aborting.")
        return 1

    state = load_state()

    market_snapshot = build_market_snapshot(symbols)
    category = pick_category(cfg["category_weights"])

    symbol = random.choice(symbols) if market_snapshot else None

    if symbol and in_cooldown(state, "symbol", symbol, posting_cfg["cooldown_hours"]["same_symbol"]):
        candidates = [s for s in symbols if not in_cooldown(
            state, "symbol", s, posting_cfg["cooldown_hours"]["same_symbol"]
        )]
        symbol = random.choice(candidates) if candidates else None

    whale_data_provided = False
    if category in ("binance_news", "general_news", "macro_news"):
        stories = get_top_stories(symbols, max_stories=3)
        untrusted_text = build_news_untrusted_text(stories)
        topic = stories[0]["title"] if stories else "market_update"
        allow_cashtag = symbol is not None
        trusted_data_text = build_trusted_data_text(symbol, market_snapshot) if symbol else "No symbol-specific data for this post."
    elif category == "events":
        prev_snapshot = state.get("whale_watch", {})
        current_snapshot = get_watchlist_snapshot()
        eth_price = market_snapshot.get("ETH", {}).get("price")
        moves = detect_significant_moves(prev_snapshot, current_snapshot, eth_price)
        state["whale_watch"] = current_snapshot
        save_state(state)
        if not moves:
            print("No significant public on-chain moves detected, skipping this run.")
            return 0
        whale_data_provided = True
        untrusted_text = "\n".join(moves)
        topic = "onchain_watchlist_move"
        allow_cashtag = symbol is not None
        trusted_data_text = build_trusted_data_text(symbol, market_snapshot) if symbol else "No symbol-specific market data."
    else:
        untrusted_text = ""
        topic = category
        allow_cashtag = symbol is not None
        trusted_data_text = build_trusted_data_text(symbol, market_snapshot) if symbol else "General crypto education/context post."

    if topic and in_cooldown(state, "topic", topic, posting_cfg["cooldown_hours"]["same_topic"]):
        print(f"Topic '{topic}' is in cooldown, skipping this run.")
        return 0

    hook_style = pick_hook_style(state)

    result = generate_post(
        trusted_data_text=trusted_data_text,
        data_snapshot=market_snapshot,
        untrusted_text=untrusted_text,
        allow_cashtag=allow_cashtag,
        hook_style=hook_style,
        whale_data_provided=whale_data_provided,
    )

    if not result or not result.get("text"):
        reason = result.get("reject_reason") if result else "no_ai_output"
        print(f"No valid content produced ({reason}). Skipping this run.")
        record_post(
            state, category=category, symbol=symbol, topic=topic, text=reason or "rejected",
            ai_provider=result.get("provider") if result else None,
            data_snapshot=market_snapshot, quality_score=0, published=False,
            hook_type=hook_style,
        )
        return 0

    text = result["text"]
    score = result["quality_score"]

    if score < posting_cfg["min_quality_score"]:
        print(f"Quality score {score} below threshold, skipping publish.")
        record_post(
            state, category=category, symbol=symbol, topic=topic, text=text,
            ai_provider=result["provider"], data_snapshot=market_snapshot,
            quality_score=score, published=False, hook_type=hook_style,
        )
        return 0

    if is_duplicate(state, text, posting_cfg["dedup_window_days"]):
        print("Duplicate content detected, skipping publish.")
        return 0

    from publisher import post_to_square
    publish_result = post_to_square(text, API_KEY)

    record_post(
        state, category=category, symbol=symbol, topic=topic, text=text,
        ai_provider=result["provider"], data_snapshot=market_snapshot,
        quality_score=score, published=(publish_result.status == "published"),
        hook_type=hook_style,
    )

    print(f"Publish status: {publish_result.status} detail={publish_result.detail}")
    return 0 if publish_result.status in ("published", "unknown") else 1


if __name__ == "__main__":
    sys.exit(run())
