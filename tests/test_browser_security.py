import unittest

from utils import build_chrome_arguments


class BrowserSecurityTests(unittest.TestCase):
    def test_headless_defaults_do_not_enable_insecure_flags_or_remote_debugging(self):
        arguments = build_chrome_arguments(headless=True)

        self.assertIn("--headless=new", arguments)
        self.assertNotIn("--ignore-certificate-errors", arguments)
        self.assertNotIn("--allow-running-insecure-content", arguments)
        self.assertNotIn("--disable-web-security", arguments)
        self.assertNotIn("--remote-debugging-port=9222", arguments)

    def test_legacy_browser_flags_require_explicit_opt_in(self):
        arguments = build_chrome_arguments(
            headless=True,
            allow_insecure_browser_flags=True,
            allow_remote_debugging=True,
        )

        self.assertIn("--ignore-certificate-errors", arguments)
        self.assertIn("--allow-running-insecure-content", arguments)
        self.assertIn("--disable-web-security", arguments)
        self.assertIn("--remote-debugging-port=9222", arguments)


if __name__ == "__main__":
    unittest.main()
