from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import run_housing_chat


class HousingChatCliTests(unittest.TestCase):
    def test_chat_cli_starts_and_quits_without_llm_or_browser(self) -> None:
        stdout = io.StringIO()
        with patch("sys.argv", ["run_housing_chat.py", "--max-listings", "2"]):
            with patch("builtins.input", return_value="quit"):
                with patch("sys.stdout", stdout):
                    run_housing_chat.main()

        output = stdout.getvalue()
        self.assertIn("Housing chat agent", output)
        self.assertIn("Goodbye.", output)


if __name__ == "__main__":
    unittest.main()
