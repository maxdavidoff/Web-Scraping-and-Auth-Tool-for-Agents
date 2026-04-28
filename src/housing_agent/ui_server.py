from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from src.housing_agent import DEFAULT_MISTRAL_MODEL
from src.housing_agent.interactive_agent import AgentTurn, InteractiveHousingAgent
from src.ohana_agent.config import DATA_DIR, PROJECT_ROOT


STATIC_DIR = Path(__file__).resolve().parent / "ui_static"
DEFAULT_ARTIFACT_ROOTS = (
    DATA_DIR / "debug",
    DATA_DIR / "raw",
    DATA_DIR / "processed",
)


class HousingUiState:
    def __init__(self, agent: InteractiveHousingAgent, artifact_roots: tuple[Path, ...] = DEFAULT_ARTIFACT_ROOTS) -> None:
        self.agent = agent
        self.artifact_roots = tuple(root.resolve() for root in artifact_roots)
        self.lock = threading.Lock()

    def handle_message(self, message: str) -> dict[str, Any]:
        with self.lock:
            turn = self.agent.handle_user_message(message)
            return turn_to_response(turn)

    def reset(self) -> dict[str, Any]:
        with self.lock:
            turn = self.agent.reset()
            return turn_to_response(turn)

    def current_state(self) -> dict[str, Any]:
        with self.lock:
            payload = self.agent.current_state_payload()
            return {"turn": {"state": payload.get("state"), "message": "", "debug_message": ""}, "payload": payload}


class HousingUiRequestHandler(BaseHTTPRequestHandler):
    server_version = "HousingAgentUI/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_static(STATIC_DIR / "index.html")
            return
        if parsed.path.startswith("/static/"):
            relative = parsed.path.removeprefix("/static/").strip("/")
            self._serve_static(STATIC_DIR / relative)
            return
        if parsed.path == "/api/state":
            self._write_json(self.ui_state.current_state())
            return
        if parsed.path == "/api/health":
            self._write_json({"status": "ok"})
            return
        if parsed.path == "/artifact":
            self._serve_artifact(parsed.query)
            return
        self._write_error(HTTPStatus.NOT_FOUND, "Not found.")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/chat":
            try:
                body = self._read_json_body()
            except ValueError as exc:
                self._write_error(HTTPStatus.BAD_REQUEST, str(exc))
                return
            message = str(body.get("message", "")).strip()
            if not message:
                self._write_error(HTTPStatus.BAD_REQUEST, "message is required.")
                return
            self._write_json(self.ui_state.handle_message(message))
            return
        if parsed.path == "/api/reset":
            self._write_json(self.ui_state.reset())
            return
        self._write_error(HTTPStatus.NOT_FOUND, "Not found.")

    @property
    def ui_state(self) -> HousingUiState:
        return self.server.ui_state  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("content-length", "0") or "0")
        if content_length <= 0:
            return {}
        raw = self.rfile.read(content_length).decode("utf-8")
        if not raw.strip():
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Request body must be JSON.") from exc
        return payload if isinstance(payload, dict) else {}

    def _serve_static(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            if STATIC_DIR.resolve() not in resolved.parents and resolved != STATIC_DIR.resolve():
                self._write_error(HTTPStatus.FORBIDDEN, "Static path is not allowed.")
                return
            if not resolved.is_file():
                self._write_error(HTTPStatus.NOT_FOUND, "Static file not found.")
                return
            self._write_file(resolved)
        except OSError as exc:
            self._write_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _serve_artifact(self, query: str) -> None:
        values = parse_qs(query)
        raw_path = values.get("path", [""])[0]
        if not raw_path:
            self._write_error(HTTPStatus.BAD_REQUEST, "path is required.")
            return
        try:
            artifact = resolve_artifact_path(raw_path, self.ui_state.artifact_roots)
        except ValueError as exc:
            self._write_error(HTTPStatus.FORBIDDEN, str(exc))
            return
        if not artifact.is_file():
            self._write_error(HTTPStatus.NOT_FOUND, "Artifact file not found.")
            return
        self._write_file(artifact)

    def _write_file(self, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_error(self, status: HTTPStatus, message: str) -> None:
        self._write_json({"error": message}, status)


class HousingUiServer(ThreadingHTTPServer):
    ui_state: HousingUiState


def turn_to_response(turn: AgentTurn) -> dict[str, Any]:
    payload = dict(turn.json_payload or {})
    return {
        "turn": {
            "state": turn.state,
            "message": user_facing_message(turn, payload),
            "debug_message": turn.message,
        },
        "payload": payload,
    }


def user_facing_message(turn: AgentTurn, payload: dict[str, Any]) -> str:
    state = turn.state
    if state == "needs_clarification":
        return clarification_message(payload, turn.message)
    if state == "execution_confirmation_requested":
        providers = payload.get("proposed_execution_providers") or []
        provider_text = provider_list_text(providers)
        max_listings = payload.get("max_listings") or 10
        return f"I can search {provider_text} and show up to {max_listings} listings. Want me to run it?"
    if state == "executed":
        execution = payload.get("execution_result") or {}
        records = execution.get("records") or []
        count = len(records)
        if count == 1:
            return "I found 1 listing. I put the match and verification notes on the right."
        if count:
            return f"I found {count} listings. I put the matches and verification notes on the right."
        return "I did not find listings for that search. I put the provider status and next checks on the right."
    if state == "reset":
        return "Reset complete. What are you looking for?"
    if state == "planned":
        return "I have a search plan ready. Review it on the right."
    return turn.message


def clarification_message(payload: dict[str, Any], fallback: str) -> str:
    readiness = payload.get("search_readiness") or {}
    questions = [str(question).strip() for question in readiness.get("followup_questions") or [] if str(question).strip()]
    if len(questions) == 1:
        return questions[0]
    if len(questions) > 1:
        return "Two details would help:\n" + "\n".join(f"- {question}" for question in questions[:2])
    return fallback.strip()


def provider_list_text(providers: list[str] | tuple[str, ...]) -> str:
    labels = {
        "ohana": "Ohana",
        "rentalsource": "RentalSource",
        "affordablehousing": "AffordableHousing",
    }
    names = [labels.get(str(provider), str(provider)) for provider in providers]
    if not names:
        return "the selected provider"
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def resolve_artifact_path(raw_path: str, artifact_roots: tuple[Path, ...] = DEFAULT_ARTIFACT_ROOTS) -> Path:
    decoded = unquote(raw_path)
    path = Path(decoded)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    for root in artifact_roots:
        root_resolved = root.resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            return resolved
    allowed = ", ".join(str(root) for root in artifact_roots)
    raise ValueError(f"Artifact must be inside one of: {allowed}")


def create_ui_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    agent: InteractiveHousingAgent | None = None,
    artifact_roots: tuple[Path, ...] = DEFAULT_ARTIFACT_ROOTS,
) -> HousingUiServer:
    server = HousingUiServer((host, port), HousingUiRequestHandler)
    server.ui_state = HousingUiState(agent or InteractiveHousingAgent(), artifact_roots)
    return server


def build_agent_from_args(args: argparse.Namespace) -> InteractiveHousingAgent:
    return InteractiveHousingAgent(
        model=args.model,
        providers=args.providers,
        max_listings=args.max_listings,
        scrolls=args.scrolls,
        headless=not args.headed,
        state_file=args.state_file,
        selectors_file=args.selectors_file,
        fetch_listing_api=args.fetch_listing_api,
        capture_detail_urls=args.capture_detail_urls,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local housing search web UI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind.")
    parser.add_argument("--open", action="store_true", help="Open the UI in the default browser.")
    parser.add_argument("--model", default=DEFAULT_MISTRAL_MODEL, help="Mistral model to use.")
    parser.add_argument("--providers", nargs="+", default=None, help="Optional provider subset.")
    parser.add_argument("--max-listings", type=int, default=10, help="Maximum listings per provider.")
    parser.add_argument("--scrolls", type=int, default=3, help="Browser scroll count per provider when executing.")
    parser.add_argument("--headed", action="store_true", help="Show browser windows when executing live scrapers.")
    parser.add_argument("--state-file", default=None, help="Optional saved browser state file.")
    parser.add_argument("--selectors-file", default=None, help="Optional selector file.")
    parser.add_argument("--fetch-listing-api", action="store_true", help="Enable provider detail/API enrichment.")
    parser.add_argument("--capture-detail-urls", action="store_true", help="Capture detail URLs where supported.")
    return parser


def run_from_args(args: argparse.Namespace) -> None:
    agent = build_agent_from_args(args)
    server = create_ui_server(host=args.host, port=args.port, agent=agent)
    url = f"http://{args.host}:{server.server_address[1]}"
    print(f"Housing UI running at {url}")
    print("Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping housing UI.")
    finally:
        server.server_close()
