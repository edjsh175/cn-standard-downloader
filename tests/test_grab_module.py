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


if __name__ == "__main__":
    unittest.main()
