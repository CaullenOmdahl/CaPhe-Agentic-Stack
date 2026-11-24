import unittest

from notes_app.notes import add_note, bulk_delete

ALICE = {"name": "alice", "role": "user"}


class Visible(unittest.TestCase):
    def test_owner_bulk_delete(self):
        store = {}
        for i in (1, 2, 3):
            add_note(store, i, "alice", "x")
        self.assertEqual(bulk_delete(store, ALICE, [1, 2]), 2)
        self.assertEqual(list(store), [3])


if __name__ == "__main__":
    unittest.main()
