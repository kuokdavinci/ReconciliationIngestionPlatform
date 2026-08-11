"""Local HTTP source for the manual ViettelPay Sprint 2 UI demo."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scripts.demo.sprint2.fixture import MockAPIError, ViettelPayMockFixture


DEFAULT_STATE_FILE = Path("mock_data/viettelpay_sprint2/mock_api_state.json")
PID_FILE = Path("/tmp/reconciliation-viettelpay-sprint2-mock.pid")
LOG_FILE = Path("/tmp/reconciliation-viettelpay-sprint2-mock.log")


def write_state(path: Path, *, failures: int) -> None:
    """Arm or disarm page 2 failure mode for the running mock server."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"remainingPage2Failures": failures}, indent=2) + "\n",
        encoding="utf-8",
    )


class MockAPIState:
    """Keep failure budget across HTTP retry attempts and scheduler runs."""

    def __init__(self, failures: int, state_file: Path | None = None) -> None:
        self.fixture = ViettelPayMockFixture()
        self.remaining_page2_failures = failures
        self.state_file = state_file

    def refresh(self) -> None:
        if self.state_file is None or not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.remaining_page2_failures = int(payload["remainingPage2Failures"])
        except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
            return


def page_response(state: MockAPIState, *, page: int, cursor: str | None) -> tuple[int, dict]:
    """Return one deterministic HTTP response without depending on a socket."""

    state.refresh()
    if page == 2 and state.remaining_page2_failures > 0:
        state.remaining_page2_failures -= 1
        if state.state_file is not None:
            write_state(state.state_file, failures=state.remaining_page2_failures)
        return 504, {
            "error": "fetch_timeout",
            "message": "Gateway timeout while fetching page 2",
            "remainingFailures": state.remaining_page2_failures,
        }
    try:
        payload = state.fixture.fetch_page(page=page, cursor=cursor)
        # Keep the internal fixture metadata (`cursorAfter`) separate from the
        # HTTP contract configured by the seeded API fetcher (`nextCursor`).
        payload["nextCursor"] = payload.pop("cursorAfter", None)
        return 200, payload
    except (ValueError, MockAPIError) as exc:
        return 400, {"error": "invalid_request", "message": str(exc)}


class MockAPIHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"status": "ok", "partner": "VIETTELPAY"})
            return
        if parsed.path != "/viettelpay/settlement":
            self._json(404, {"error": "not_found"})
            return

        query = parse_qs(parsed.query)
        try:
            page = int(query.get("page", ["1"])[0])
            cursor = query.get("cursor", [None])[0]
            state: MockAPIState = self.server.demo_state  # type: ignore[attr-defined]
            status, payload = page_response(state, page=page, cursor=cursor)
            self._json(status, payload)
        except ValueError as exc:
            self._json(400, {"error": "invalid_request", "message": str(exc)})

    def log_message(self, format: str, *args) -> None:
        print(f"[viettelpay-mock] {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="store_true", help="Start the mock in the background if needed")
    parser.add_argument("--phase2", action="store_true", help="Disable page 2 failures")
    parser.add_argument("--background", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument(
        "--page2-failures",
        type=int,
        default=3,
        help="HTTP 504 responses consumed by one APIFetcher retry cycle",
    )
    args = parser.parse_args()
    if args.page2_failures < 0:
        parser.error("--page2-failures must be non-negative")

    if args.start and args.phase2:
        parser.error("--start and --phase2 cannot be combined")
    if args.phase2:
        write_state(args.state_file, failures=0)
        return ensure_running(args.host, args.port, args.state_file)
    if args.start:
        write_state(args.state_file, failures=args.page2_failures)
        return ensure_running(args.host, args.port, args.state_file)
    if args.background:
        return serve(args.host, args.port, args.state_file)

    return serve(args.host, args.port, args.state_file)


def _pid_is_running() -> bool:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8"))
        os.kill(pid, 0)
        return True
    except (FileNotFoundError, OSError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return False


def ensure_running(host: str, port: int, state_file: Path) -> int:
    if _pid_is_running():
        print(f"ViettelPay mock API already running; state updated: {state_file}")
        return 0

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = LOG_FILE.open("a", encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "scripts.demo.sprint2.mock_api",
        "--background",
        "--host",
        host,
        "--port",
        str(port),
        "--state-file",
        str(state_file),
    ]
    subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
    log.close()
    print(f"ViettelPay mock API started in background; state: {state_file}")
    return 0


def serve(host: str, port: int, state_file: Path) -> int:
    server = ThreadingHTTPServer((host, port), MockAPIHandler)
    server.demo_state = MockAPIState(0, state_file=state_file)  # type: ignore[attr-defined]
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    print(
        f"ViettelPay mock API listening on http://{host}:{port}; "
        f"state file: {state_file}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nViettelPay mock API stopped")
    finally:
        server.server_close()
        try:
            if PID_FILE.read_text(encoding="utf-8") == str(os.getpid()):
                PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
