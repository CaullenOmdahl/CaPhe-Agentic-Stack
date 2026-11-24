import os
import sys
import unittest

sys.path.insert(0, os.environ["WORKSPACE"])
from durations.parse import parse_duration  # noqa: E402


class Hidden(unittest.TestCase):
    def test_valid(self):
        cases = {"2d4h": 187200, "1h 30m": 5400, " 5M ": 300, "1d1h1m1s": 90061, "0s": 0, "10D": 864000}
        for text, want in cases.items():
            self.assertEqual(parse_duration(text), want, text)

    def test_invalid(self):
        for text in ["", "  ", "30", "5x", "1m1h", "1h1h", "-5s", "1.5h", "1h  30m", "h", "1h30", "1 h"]:
            with self.assertRaises(ValueError, msg=repr(text)):
                parse_duration(text)


if __name__ == "__main__":
    unittest.main()
