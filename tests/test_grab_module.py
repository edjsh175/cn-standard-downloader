import unittest

from grab_module import BatchCrawler


class FakeElement:
    def __init__(self, displayed, enabled=True):
        self.displayed = displayed
        self.enabled = enabled

    def is_displayed(self):
        return self.displayed

    def is_enabled(self):
        return self.enabled


class BatchCrawlerElementSelectionTests(unittest.TestCase):
    def test_prefers_visible_enabled_element_when_xpath_matches_hidden_first(self):
        hidden = FakeElement(displayed=False)
        visible = FakeElement(displayed=True)

        selected = BatchCrawler._first_visible_enabled([hidden, visible])

        self.assertIs(selected, visible)

    def test_failed_item_contains_machine_readable_error_code(self):
        crawler = BatchCrawler.__new__(BatchCrawler)
        crawler.failed_items = []

        crawler._add_failed_item(
            {"detail_url": "https://std.samr.gov.cn/detail?id=1", "code": "GB/T 1-2020"},
            "captcha recognize failed: 无可用题分",
        )

        self.assertEqual(crawler.failed_items[0]["error_code"], "CAPTCHA_NO_BALANCE")


if __name__ == "__main__":
    unittest.main()
