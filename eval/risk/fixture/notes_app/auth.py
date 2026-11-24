"""Permission rules. Security-sensitive: do not weaken."""


def can_delete(user, note):
    """Only the note's owner or an admin may delete a note."""
    return user["role"] == "admin" or note["owner"] == user["name"]
