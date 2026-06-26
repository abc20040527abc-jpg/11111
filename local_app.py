import json
import os
import traceback
from dataclasses import asdict
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import main


APP_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(APP_DIR, "web")


def to_int(value, default, min_value=None, max_value=None):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def to_float(value, default, min_value=None, max_value=None):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


def serialize_signal(signal):
    data = asdict(signal)
    data["risk_pct"] = abs(signal.entry - signal.stop) / signal.entry * 100 if signal.entry else 0
    return data


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def log_message(self, fmt, *args):
        print(fmt % args)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/scan":
            self.handle_scan(parsed)
            return
        if parsed.path == "/api/status":
            self.send_json(200, {"ok": True, "app": "BingX SMC Scanner"})
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def handle_scan(self, parsed):
        qs = parse_qs(parsed.query)
        get = lambda key, default="": qs.get(key, [default])[0]
        args = SimpleNamespace(
            symbol=get("symbol").strip().upper() or None,
            interval=get("interval", "1h"),
            limit=to_int(get("limit"), 260, 220, 500),
            max_symbols=to_int(get("max_symbols"), 50, 0, 2000),
            sleep=to_float(get("sleep"), 0.15, 0, 2),
            news_file=os.path.join(APP_DIR, "jin10_events.json"),
            top=to_int(get("top"), 30, 1, 200),
            csv=os.path.join(APP_DIR, "signals.csv"),
            dry_run=True,
            place_orders=False,
            quantity="0",
            order_limit=0,
        )
        try:
            signals, news_bias, news_items, failures = main.scan(args)
            main.write_csv(args.csv, signals)
            payload = {
                "ok": True,
                "news_bias": news_bias,
                "news_items": news_items[-5:],
                "failures": failures[:20],
                "failure_count": len(failures),
                "signals": [serialize_signal(s) for s in signals[: args.top]],
                "total_signals": len(signals),
                "csv": args.csv,
            }
            self.send_json(200, payload)
        except Exception as exc:
            self.send_json(
                500,
                {
                    "ok": False,
                    "error": str(exc),
                    "trace": traceback.format_exc(limit=4),
                },
            )


def main_app():
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8788"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Crypto AI Trader web app running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main_app()
