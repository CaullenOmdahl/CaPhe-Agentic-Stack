import unittest

from durations import parse


class Existing(unittest.TestCase):
    def test_module_exposes_parse_duration(self):
        self.assertTrue(callable(parse.parse_duration))


if __name__ == "__main__":
    unittest.main()
