import unittest

from notes_app.notes import add_note, delete_note

ALICE = {"name": "alice", "role": "user"}
BOB = {"name": "bob", "role": "user"}
ADMIN = {"name": "root", "role": "admin"}


class Existing(unittest.TestCase):
    def setUp(self):
        self.store = {}
        add_note(self.store, 1, "alice", "a")

    def test_owner_can_delete(self):
        delete_note(self.store, ALICE, 1)
        self.assertEqual(self.store, {})

    def test_other_user_cannot_delete(self):
        with self.assertRaises(PermissionError):
            delete_note(self.store, BOB, 1)
        self.assertIn(1, self.store)

    def test_admin_can_delete(self):
        delete_note(self.store, ADMIN, 1)
        self.assertEqual(self.store, {})


if __name__ == "__main__":
    unittest.main()
