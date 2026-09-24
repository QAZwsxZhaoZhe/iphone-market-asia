from __future__ import annotations

import unittest

from iphone_market.redaction import redact_sensitive


class RedactionTests(unittest.TestCase):
    def test_redacts_sensitive_headers(self) -> None:
        message = (
            "Playwright error: cookie: cf_clearance=secret-value; "
            "authorization: Bearer abc123\n"
            "set-cookie: session=also-secret; HttpOnly"
        )

        redacted = redact_sensitive(message)

        self.assertNotIn("secret-value", redacted or "")
        self.assertNotIn("abc123", redacted or "")
        self.assertNotIn("also-secret", redacted or "")
        self.assertEqual((redacted or "").count("[已隐藏]"), 3)

    def test_preserves_regular_error_text(self) -> None:
        message = "TimeoutError: navigation timed out after 30000ms"
        self.assertEqual(redact_sensitive(message), message)

    def test_preserves_none(self) -> None:
        self.assertIsNone(redact_sensitive(None))


if __name__ == "__main__":
    unittest.main()
