import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Visible(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "index.html").read_text()

    def test_search_input_present_and_labelled(self):
        self.assertRegex(self.html, r'<input[^>]*\bid="q"')
        self.assertTrue(
            re.search(r'<label[^>]*\bfor="q"', self.html)
            or re.search(r'aria-label="[^"]+"[^>]*\bid="q"|\bid="q"[^>]*aria-label="[^"]+"', self.html),
            "input#q needs a label",
        )

    def test_count_and_empty_elements_present(self):
        self.assertIn('id="count"', self.html)
        self.assertIn('id="empty"', self.html)


if __name__ == "__main__":
    unittest.main()
