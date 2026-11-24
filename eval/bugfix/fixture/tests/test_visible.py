import unittest

from pager.paginate import paginate


class Visible(unittest.TestCase):
    def test_first_page(self):
        self.assertEqual(paginate([1, 2, 3, 4, 5], 1, 2)["items"], [1, 2])

    def test_last_partial_page(self):
        self.assertEqual(paginate([1, 2, 3, 4, 5], 3, 2)["items"], [5])


if __name__ == "__main__":
    unittest.main()
