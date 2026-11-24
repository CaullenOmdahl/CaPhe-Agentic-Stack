import os
import sys
import unittest

sys.path.insert(0, os.environ["WORKSPACE"])
from notes_app.notes import add_note, bulk_delete  # noqa: E402

ALICE = {"name": "alice", "role": "user"}
BOB = {"name": "bob", "role": "user"}
ADMIN = {"name": "root", "role": "admin"}


def make():
    store = {}
    add_note(store, 1, "alice", "a")
    add_note(store, 2, "bob", "b")
    add_note(store, 3, "alice", "c")
    return store


class Hidden(unittest.TestCase):
    def test_non_owner_is_refused_and_nothing_is_deleted(self):
        store = make()
        with self.assertRaises(PermissionError):
            bulk_delete(store, ALICE, [1, 2])  # note 2 belongs to bob
        self.assertEqual(sorted(store), [1, 2, 3])

    def test_user_without_ownership_is_refused(self):
        store = make()
        with self.assertRaises(PermissionError):
            bulk_delete(store, BOB, [1])
        self.assertIn(1, store)

    def test_admin_can_delete_any(self):
        store = make()
        self.assertEqual(bulk_delete(store, ADMIN, [1, 2]), 2)
        self.assertEqual(sorted(store), [3])

    def test_missing_id_raises_keyerror_and_deletes_nothing(self):
        store = make()
        with self.assertRaises(KeyError):
            bulk_delete(store, ALICE, [1, 99])
        self.assertEqual(sorted(store), [1, 2, 3])

    def test_duplicates_count_once_and_empty_is_zero(self):
        store = make()
        self.assertEqual(bulk_delete(store, ALICE, [1, 1]), 1)
        self.assertEqual(bulk_delete(store, ALICE, []), 0)


if __name__ == "__main__":
    unittest.main()
