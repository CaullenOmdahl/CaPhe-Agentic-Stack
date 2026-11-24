from notes_app.auth import can_delete


def add_note(store, note_id, owner, text):
    store[note_id] = {"id": note_id, "owner": owner, "text": text}


def delete_note(store, user, note_id):
    """Delete one note. KeyError if missing, PermissionError if not allowed."""
    note = store[note_id]
    if not can_delete(user, note):
        raise PermissionError(f"{user['name']} may not delete note {note_id}")
    del store[note_id]
