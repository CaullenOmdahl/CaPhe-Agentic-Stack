import os
import sys
import unittest

sys.path.insert(0, os.environ["WORKSPACE"])
from pager.paginate import paginate  # noqa: E402


class Hidden(unittest.TestCase):
    def test_pages_cover_all_items_in_order(self):
        for n in range(0, 12):
            for per in range(1, 6):
                items = list(range(n))
                total = paginate(items, 1, per)["total_pages"]
                seen = []
                for p in range(1, total + 1):
                    seen += paginate(items, p, per)["items"]
                self.assertEqual(seen, items, (n, per))

    def test_total_pages(self):
        self.assertEqual(paginate(list(range(5)), 1, 2)["total_pages"], 3)
        self.assertEqual(paginate(list(range(4)), 1, 2)["total_pages"], 2)
        self.assertEqual(paginate([], 1, 2)["total_pages"], 0)

    def test_shape_and_validation(self):
        self.assertEqual(set(paginate([1], 1, 1)), {"items", "page", "total_pages"})
        with self.assertRaises(ValueError):
            paginate([1], 0, 1)
        self.assertEqual(paginate([1, 2, 3], 5, 2)["items"], [])


if __name__ == "__main__":
    unittest.main()
