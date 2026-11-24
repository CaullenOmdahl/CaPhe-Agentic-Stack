import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Existing(unittest.TestCase):
    def test_page_has_list_and_loads_script(self):
        html = (ROOT / "index.html").read_text()
        self.assertIn('id="list"', html)
        self.assertRegex(html, r'<script[^>]+src="app\.js"')

    def test_items_defined(self):
        js = (ROOT / "app.js").read_text()
        self.assertRegex(js, r"ITEMS\s*=\s*\[")


if __name__ == "__main__":
    unittest.main()
