from __future__ import annotations

import unittest

from src.demo_service import format_greeting


class GreetingTests(unittest.TestCase):
    def test_default_greeting_mentions_weavert(self) -> None:
        self.assertEqual(format_greeting(), "Hello, WeaveRT.")

    def test_named_greeting_strips_whitespace(self) -> None:
        self.assertEqual(format_greeting("  Demo  "), "Hello, Demo.")


if __name__ == "__main__":
    unittest.main()
