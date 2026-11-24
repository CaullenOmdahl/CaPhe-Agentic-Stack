import unittest

from durations.parse import parse_duration


class Visible(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(parse_duration("90s"), 90)

    def test_combined(self):
        self.assertEqual(parse_duration("1h30m"), 5400)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_duration("")


if __name__ == "__main__":
    unittest.main()
