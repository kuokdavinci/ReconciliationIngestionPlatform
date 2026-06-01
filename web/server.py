from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class DashboardHandler(SimpleHTTPRequestHandler):
    api_target = "http://localhost:8000"

    def do_GET(self) -> None:
        if self.path.startswith("/api/"):
            self.proxy_api()
            return
        super().do_GET()

    def proxy_api(self) -> None:
        target = self.api_target.rstrip("/") + self.path
        request = Request(target, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=60) as response:
                body = response.read()
                self.send_response(response.status)
                self.send_header("Content-Type", response.headers.get("Content-Type", "application/json"))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
        except HTTPError as exc:
            body = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.end_headers()
            self.wfile.write(body)
        except URLError as exc:
            body = json.dumps({"detail": f"Backend API unavailable: {exc.reason}"}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Adapter dashboard with /api proxy.")
    parser.add_argument("--port", type=int, default=5173)
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()

    DashboardHandler.api_target = args.api
    web_dir = Path(__file__).resolve().parent

    class Handler(DashboardHandler):
        def __init__(self, *handler_args, **handler_kwargs):
            super().__init__(*handler_args, directory=str(web_dir), **handler_kwargs)

    server = ThreadingHTTPServer(("localhost", args.port), Handler)
    print(f"Dashboard: http://localhost:{args.port}")
    print(f"API proxy:  /api -> {args.api}")
    server.serve_forever()


if __name__ == "__main__":
    main()
