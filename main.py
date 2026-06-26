import argparse
import csv
import hashlib
import hmac
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone


BINGX_BASE_URL = "https://open-api.bingx.com"
DEFAULT_INTERVAL = "1h"
DEFAULT_LIMIT = 260


@dataclass
class Candle:
    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    symbol: str
    side: str
    entry: float
    stop: float
    tp_1r: float
    tp_15r: float
    rr: float
    reasons: list
    news_bias: str
    score: int
    tradingview_url: str


def http_json(path, params=None, headers=None, timeout=20):
    params = params or {}
    query = urllib.parse.urlencode(params)
    url = f"{BINGX_BASE_URL}{path}"
    if query:
        url += f"?{query}"
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "crypto-ai-trader/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    if isinstance(data, dict) and data.get("code") not in (None, 0, "0") and data.get("retCode") not in (None, 0, "0"):
        raise RuntimeError(f"BingX API error: {data}")
    return data


def sign_params(params, secret):
    query = urllib.parse.urlencode(sorted(params.items()))
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


def signed_post(path, params):
    api_key = os.getenv("BINGX_API_KEY", "")
    api_secret = os.getenv("BINGX_API_SECRET", "")
    if not api_key or not api_secret:
        raise RuntimeError("Missing BINGX_API_KEY or BINGX_API_SECRET")
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["signature"] = sign_params(params, api_secret)
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        f"{BINGX_BASE_URL}{path}",
        data=body,
        method="POST",
        headers={"X-BX-APIKEY": api_key, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_list(payload):
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    for key in ("data", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for nested in ("list", "data", "contracts"):
                if isinstance(value.get(nested), list):
                    return value[nested]
    return []


def fetch_symbols(quote_asset="USDT"):
    payload = http_json("/openApi/swap/v2/quote/contracts")
    symbols = []
    for item in extract_list(payload):
        symbol = item.get("symbol") or item.get("contractName")
        status = str(item.get("status", item.get("state", ""))).lower()
        if not symbol or quote_asset not in symbol:
            continue
        if status and status not in ("1", "trading", "online", "enable", "enabled"):
            continue
        symbols.append(symbol)
    return sorted(set(symbols))


def parse_candle(raw):
    if isinstance(raw, dict):
        ts = raw.get("time") or raw.get("openTime") or raw.get("T") or raw.get("timestamp")
        return Candle(
            int(ts),
            float(raw.get("open")),
            float(raw.get("high")),
            float(raw.get("low")),
            float(raw.get("close")),
            float(raw.get("volume", raw.get("vol", 0))),
        )
    return Candle(int(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]), float(raw[4]), float(raw[5] if len(raw) > 5 else 0))


def fetch_klines(symbol, interval, limit):
    payload = http_json("/openApi/swap/v3/quote/klines", {"symbol": symbol, "interval": interval, "limit": limit})
    candles = [parse_candle(row) for row in extract_list(payload)]
    candles.sort(key=lambda x: x.ts)
    return candles


def ema(values, period):
    if len(values) < period:
        return [None] * len(values)
    out = [None] * len(values)
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2 / (period + 1)
    last = seed
    for i in range(period, len(values)):
        last = values[i] * alpha + last * (1 - alpha)
        out[i] = last
    return out


def bollinger(values, period=20, mult=2.0):
    out = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append((None, None, None))
            continue
        window = values[i + 1 - period : i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        sd = math.sqrt(variance)
        out.append((mean, mean + mult * sd, mean - mult * sd))
    return out


def swing_points(candles, left=2, right=2):
    highs = []
    lows = []
    for i in range(left, len(candles) - right):
        window = candles[i - left : i + right + 1]
        if candles[i].high == max(c.high for c in window):
            highs.append((i, candles[i].high))
        if candles[i].low == min(c.low for c in window):
            lows.append((i, candles[i].low))
    return highs, lows


def last_before(points, index):
    prior = [p for p in points if p[0] < index]
    return prior[-1] if prior else None


def detect_smc(candles):
    highs, lows = swing_points(candles)
    i = len(candles) - 1
    last = candles[-1]
    prev = candles[-2]
    reasons = {"LONG": [], "SHORT": []}
    last_high = last_before(highs, i)
    last_low = last_before(lows, i)

    if last_high and prev.close <= last_high[1] < last.close:
        reasons["LONG"].append(f"SMC BOS: close breaks swing high {last_high[1]:.8g}")
    if last_low and prev.close >= last_low[1] > last.close:
        reasons["SHORT"].append(f"SMC BOS: close breaks swing low {last_low[1]:.8g}")

    if last_low and last.low < last_low[1] and last.close > last_low[1]:
        reasons["LONG"].append(f"SMC liquidity sweep: wicks below {last_low[1]:.8g} and closes back")
    if last_high and last.high > last_high[1] and last.close < last_high[1]:
        reasons["SHORT"].append(f"SMC liquidity sweep: wicks above {last_high[1]:.8g} and closes back")

    if len(candles) >= 4:
        c1 = candles[-3]
        c3 = candles[-1]
        if c1.high < c3.low:
            reasons["LONG"].append(f"SMC bullish FVG: gap {c1.high:.8g}-{c3.low:.8g}")
        if c1.low > c3.high:
            reasons["SHORT"].append(f"SMC bearish FVG: gap {c3.high:.8g}-{c1.low:.8g}")

    return reasons, highs, lows


def load_news_bias(path):
    url = os.getenv("JIN10_API_URL", "")
    token = os.getenv("JIN10_API_TOKEN", "")
    items = []
    if url:
        headers = {"User-Agent": "crypto-ai-trader/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            items = extract_list(data)
        except Exception as exc:
            return "NEUTRAL", [f"Jin10 fetch failed: {exc}"]
    elif os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else extract_list(data)

    texts = []
    for item in items[-50:]:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, dict):
            texts.append(" ".join(str(item.get(k, "")) for k in ("title", "content", "summary", "text")))
    joined = " ".join(texts).lower()
    risk_on_words = ("降息", "宽松", "寬鬆", "etf流入", "利好", "risk-on", "lower rates", "dovish", "stimulus")
    risk_off_words = ("加息", "衰退", "监管", "監管", "战争", "戰爭", "爆仓", "爆倉", "risk-off", "hawkish", "higher rates")
    on = sum(joined.count(w.lower()) for w in risk_on_words)
    off = sum(joined.count(w.lower()) for w in risk_off_words)
    if on > off:
        return "RISK_ON", texts[-5:]
    if off > on:
        return "RISK_OFF", texts[-5:]
    return "NEUTRAL", texts[-5:]


def market_reasons(candles):
    closes = [c.close for c in candles]
    ema200 = ema(closes, 200)
    bb = bollinger(closes)
    last = candles[-1]
    mid, upper, lower = bb[-1]
    reasons = {"LONG": [], "SHORT": []}
    if ema200[-1] is None or lower is None or upper is None:
        return reasons

    ema_bullish = last.close > ema200[-1]
    ema_bearish = last.close < ema200[-1]
    long_bb = []
    short_bb = []
    if last.low <= lower and last.close > lower:
        long_bb.append(f"Bollinger rebound: low touches lower band {lower:.8g}")
    if last.close > upper:
        long_bb.append(f"Bollinger breakout: close above upper band {upper:.8g}")
    if last.high >= upper and last.close < upper:
        short_bb.append(f"Bollinger rejection: high touches upper band {upper:.8g}")
    if last.close < lower:
        short_bb.append(f"Bollinger breakdown: close below lower band {lower:.8g}")

    if ema_bullish and long_bb:
        reasons["LONG"].append(f"EMA200 bullish filter: close {last.close:.8g} > EMA200 {ema200[-1]:.8g}")
        reasons["LONG"].extend(long_bb)
    if ema_bearish and short_bb:
        reasons["SHORT"].append(f"EMA200 bearish filter: close {last.close:.8g} < EMA200 {ema200[-1]:.8g}")
        reasons["SHORT"].extend(short_bb)
    return reasons


def build_signal(symbol, candles, news_bias):
    smc, highs, lows = detect_smc(candles)
    tech = market_reasons(candles)
    last = candles[-1]
    candidates = []
    for side in ("LONG", "SHORT"):
        reasons = smc[side] + tech[side]
        if not reasons:
            continue
        if news_bias == "RISK_ON" and side == "SHORT":
            reasons.append("News caution: Jin10 bias is risk-on")
        if news_bias == "RISK_OFF" and side == "LONG":
            reasons.append("News caution: Jin10 bias is risk-off")
        entry = last.close
        if side == "LONG":
            stop_point = last_before(lows, len(candles) - 1)
            stop = stop_point[1] if stop_point else min(c.low for c in candles[-20:])
            risk = entry - stop
            if risk <= 0:
                continue
            tp_1r = entry + risk
            tp_15r = entry + risk * 1.5
        else:
            stop_point = last_before(highs, len(candles) - 1)
            stop = stop_point[1] if stop_point else max(c.high for c in candles[-20:])
            risk = stop - entry
            if risk <= 0:
                continue
            tp_1r = entry - risk
            tp_15r = entry - risk * 1.5
        score = len([r for r in reasons if not r.startswith("News caution")])
        candidates.append(
            Signal(
                symbol=symbol,
                side=side,
                entry=entry,
                stop=stop,
                tp_1r=tp_1r,
                tp_15r=tp_15r,
                rr=1.5,
                reasons=reasons,
                news_bias=news_bias,
                score=score,
                tradingview_url=f"https://www.tradingview.com/chart/?symbol=BINGX:{symbol.replace('-', '')}.P",
            )
        )
    return candidates


def scan(args):
    news_bias, news_items = load_news_bias(args.news_file)
    symbols = [args.symbol] if args.symbol else fetch_symbols()
    if args.max_symbols:
        symbols = symbols[: args.max_symbols]
    signals = []
    failures = []
    for n, symbol in enumerate(symbols, start=1):
        try:
            candles = fetch_klines(symbol, args.interval, args.limit)
            if len(candles) < 220:
                continue
            signals.extend(build_signal(symbol, candles, news_bias))
        except Exception as exc:
            failures.append(f"{symbol}: {exc}")
        if args.sleep and n % 10 == 0:
            time.sleep(args.sleep)
    signals.sort(key=lambda x: (x.score, abs(x.entry - x.stop) / x.entry), reverse=True)
    return signals, news_bias, news_items, failures


def write_csv(path, signals):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "side", "entry", "stop", "tp_1r", "tp_1_5r", "score", "news_bias", "reasons", "tradingview"])
        for s in signals:
            writer.writerow([s.symbol, s.side, s.entry, s.stop, s.tp_1r, s.tp_15r, s.score, s.news_bias, " | ".join(s.reasons), s.tradingview_url])


def print_signals(signals, news_bias, news_items, failures, limit):
    print(f"Jin10/news bias: {news_bias}")
    if news_items:
        print("Recent news used:")
        for item in news_items[-3:]:
            print(f"- {item[:160]}")
    print("")
    if not signals:
        print("No symbols matched the strategy.")
        return
    for s in signals[:limit]:
        print(f"{s.symbol} {s.side} score={s.score}")
        print(f"  entry={s.entry:.8g} stop={s.stop:.8g} tp1R={s.tp_1r:.8g} tp1.5R={s.tp_15r:.8g}")
        print(f"  TradingView: {s.tradingview_url}")
        for r in s.reasons:
            print(f"  - {r}")
    if failures:
        print("")
        print(f"Skipped {len(failures)} symbols due to API/parse errors. First 5:")
        for f in failures[:5]:
            print(f"  - {f}")


def maybe_place_orders(signals, args):
    if not args.place_orders or args.dry_run:
        return
    for s in signals[: args.order_limit]:
        side = "BUY" if s.side == "LONG" else "SELL"
        params = {
            "symbol": s.symbol,
            "side": side,
            "positionSide": s.side,
            "type": "MARKET",
            "quantity": args.quantity,
        }
        print(f"Placing {s.symbol} {s.side}: {json.dumps(params)}")
        print(signed_post("/openApi/swap/v2/trade/order", params))


def main():
    parser = argparse.ArgumentParser(description="BingX crypto SMC/EMA200/Bollinger scanner with Jin10 news bias.")
    parser.add_argument("--symbol", help="Only scan one symbol, e.g. BTC-USDT")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--max-symbols", type=int, default=0, help="Limit scan count for testing.")
    parser.add_argument("--sleep", type=float, default=0.15, help="Pause every 10 symbols to reduce rate-limit risk.")
    parser.add_argument("--news-file", default="jin10_events.json")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--csv", default="signals.csv")
    parser.add_argument("--dry-run", action="store_true", help="Force no live orders even when --place-orders is set.")
    parser.add_argument("--place-orders", action="store_true", help="Danger: send market orders to BingX.")
    parser.add_argument("--quantity", default="0.001")
    parser.add_argument("--order-limit", type=int, default=1)
    args = parser.parse_args()

    signals, news_bias, news_items, failures = scan(args)
    print_signals(signals, news_bias, news_items, failures, args.top)
    write_csv(args.csv, signals)
    maybe_place_orders(signals, args)
    print(f"\nCSV saved: {os.path.abspath(args.csv)}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("Interrupted")
