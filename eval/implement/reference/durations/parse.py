"""Parse human duration strings such as '1h30m' into seconds."""
import re

_MULTIPLIERS = (86400, 3600, 60, 1)
_PATTERN = re.compile(r"(?:(\d+)d)?(?: ?(\d+)h)?(?: ?(\d+)m)?(?: ?(\d+)s)?")


def parse_duration(text):
    if not isinstance(text, str):
        raise ValueError("duration must be a string")
    cleaned = text.strip().lower()
    match = _PATTERN.fullmatch(cleaned)
    if not cleaned or match is None:
        raise ValueError(f"invalid duration: {text!r}")
    return sum(int(n) * mult for n, mult in zip(match.groups(), _MULTIPLIERS) if n)
