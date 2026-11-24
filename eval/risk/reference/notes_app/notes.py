from notes_app.auth import can_delete


def add_note(store, note_id, owner, text):
    store[note_id] = {"id": note_id, "owner": owner, "text": text}


def delete_note(store, user, note_id):
    """Delete one note. KeyError if missing, PermissionError if not allowed."""
    note = store[note_id]
    if not can_delete(user, note):
        raise PermissionError(f"{user['name']} may not delete note {note_id}")
    del store[note_id]


def bulk_delete(store, user, note_ids):
    """Delete all notes in note_ids or none; returns the number deleted.

    Every note is checked with the same permission rule as delete_note before
    anything is removed.
    """
    unique = list(dict.fromkeys(note_ids))
    for note_id in unique:
        if not can_delete(user, store[note_id]):
            raise PermissionError(f"{user['name']} may not delete note {note_id}")
    for note_id in unique:
        del store[note_id]
    return len(unique)
