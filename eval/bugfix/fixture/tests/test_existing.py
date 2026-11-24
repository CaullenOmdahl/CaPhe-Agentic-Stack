import unittest

from pager.paginate import paginate


class Existing(unittest.TestCase):
    def test_invalid_args(self):
        with self.assertRaises(ValueError):
            paginate([1, 2, 3], 0, 2)
        with self.assertRaises(ValueError):
            paginate([1, 2, 3], 1, 0)

    def test_beyond_end_is_empty(self):
        self.assertEqual(paginate([1, 2, 3], 99, 2)["items"], [])

    def test_does_not_mutate_input(self):
        data = [1, 2, 3, 4]
        paginate(data, 1, 2)
        self.assertEqual(data, [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
