from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from src.housing_agent.ui_server import create_ui_server, resolve_artifact_path, turn_to_response
from src.housing_agent.interactive_agent import AgentTurn


class FakeAgent:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.reset_called = False

    def handle_user_message(self, message: str) -> AgentTurn:
        self.messages.append(message)
        return AgentTurn(
            state="execution_confirmation_requested",
            message=f"Verbose plan details with reasoning for {message}. Search URL: https://example.test/search",
            json_payload={
                "state": "execution_confirmation_requested",
                "pending_execution_confirmation": True,
                "proposed_execution_providers": ["ohana"],
                "max_listings": 5,
                "intent": {"location": "Boston, MA"},
            },
        )

    def reset(self) -> AgentTurn:
        self.reset_called = True
        return AgentTurn(state="reset", message="Reset complete.", json_payload={"state": "reset"})

    def current_state_payload(self):
        return {"state": "collecting", "intent": None}


class HousingUiServerTests(unittest.TestCase):
    def test_static_ui_keeps_debug_panels_separate_from_chat(self) -> None:
        index = Path("src/housing_agent/ui_static/index.html").read_text(encoding="utf-8")
        app = Path("src/housing_agent/ui_static/app.js").read_text(encoding="utf-8")

        self.assertIn("Developer details", index)
        self.assertIn("debugMessagePanel", index)
        self.assertIn("summaryPanel", index)
        self.assertIn("renderDebugMessage", app)
        self.assertIn("buildRankingIndex", app)
        self.assertIn("execution?.records", app)

    def test_turn_to_response_keeps_debug_message_and_concises_confirmation(self) -> None:
        response = turn_to_response(
            AgentTurn(
                state="execution_confirmation_requested",
                message="Verbose provider reasoning. Search URL: https://example.test/search",
                json_payload={
                    "state": "execution_confirmation_requested",
                    "pending_execution_confirmation": True,
                    "proposed_execution_providers": ["ohana"],
                    "max_listings": 5,
                    "intent": {"location": "Boston"},
                },
            )
        )

        self.assertEqual(response["turn"]["state"], "execution_confirmation_requested")
        self.assertEqual(response["turn"]["message"], "I can search Ohana and show up to 5 listings. Want me to run it?")
        self.assertEqual(response["turn"]["debug_message"], "Verbose provider reasoning. Search URL: https://example.test/search")
        self.assertEqual(response["payload"]["intent"]["location"], "Boston")

    def test_turn_to_response_concises_clarification_from_readiness_questions(self) -> None:
        response = turn_to_response(
            AgentTurn(
                state="needs_clarification",
                message="Reasoning summary.\n\nWhat is your budget?",
                json_payload={
                    "state": "needs_clarification",
                    "search_readiness": {
                        "reasoning_summary": "Reasoning summary.",
                        "followup_questions": [
                            "What is your maximum monthly budget?",
                            "How many bedrooms do you need?",
                        ],
                    },
                },
            )
        )

        self.assertEqual(
            response["turn"]["message"],
            "Two details would help:\n- What is your maximum monthly budget?\n- How many bedrooms do you need?",
        )
        self.assertIn("Reasoning summary", response["turn"]["debug_message"])

    def test_turn_to_response_concises_executed_state_without_urls(self) -> None:
        response = turn_to_response(
            AgentTurn(
                state="executed",
                message=(
                    "Search execution finished. Provider reasoning. "
                    "https://liveohana.ai/listing/example data/raw/fake.jsonl"
                ),
                json_payload={
                    "state": "executed",
                    "execution_result": {
                        "records": [
                            {"title": "A", "listing_url": "https://liveohana.ai/listing/a"},
                            {"title": "B", "listing_url": "https://liveohana.ai/listing/b"},
                        ]
                    },
                },
            )
        )

        self.assertEqual(response["turn"]["message"], "I found 2 listings. I put the matches and verification notes on the right.")
        self.assertNotIn("https://", response["turn"]["message"])
        self.assertNotIn("data/raw", response["turn"]["message"])
        self.assertIn("https://liveohana.ai/listing/example", response["turn"]["debug_message"])

    def test_resolve_artifact_path_allows_only_configured_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "search_page.png"
            artifact.write_text("fake", encoding="utf-8")

            self.assertEqual(resolve_artifact_path(str(artifact), (root,)), artifact.resolve())
            with self.assertRaises(ValueError):
                resolve_artifact_path("/etc/passwd", (root,))

    def test_http_chat_reset_and_artifact_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            artifact = root / "debug.txt"
            artifact.write_text("artifact", encoding="utf-8")
            agent = FakeAgent()
            server = create_ui_server(host="127.0.0.1", port=0, agent=agent, artifact_roots=(root,))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                port = server.server_address[1]
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                try:
                    conn.request("GET", "/")
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertIn(b"Housing Search Agent", response.read())

                    body = json.dumps({"message": "hello"}).encode("utf-8")
                    conn.request("POST", "/api/chat", body=body, headers={"Content-Type": "application/json"})
                    response = conn.getresponse()
                    payload = json.loads(response.read())
                    self.assertEqual(response.status, 200)
                    self.assertEqual(
                        payload["turn"]["message"],
                        "I can search Ohana and show up to 5 listings. Want me to run it?",
                    )
                    self.assertIn("Verbose plan details", payload["turn"]["debug_message"])
                    self.assertEqual(agent.messages, ["hello"])

                    conn.request("GET", f"/artifact?path={artifact}")
                    response = conn.getresponse()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.read(), b"artifact")

                    conn.request("POST", "/api/reset", body=b"{}", headers={"Content-Type": "application/json"})
                    response = conn.getresponse()
                    payload = json.loads(response.read())
                    self.assertEqual(payload["turn"]["state"], "reset")
                    self.assertEqual(payload["turn"]["message"], "Reset complete. What are you looking for?")
                    self.assertEqual(payload["turn"]["debug_message"], "Reset complete.")
                    self.assertTrue(agent.reset_called)
                finally:
                    conn.close()
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
