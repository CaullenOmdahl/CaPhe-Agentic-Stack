In this repository, `durations/parse.py` has a stub `parse_duration(text)` that raises `NotImplementedError`.

Implement it. It converts a human duration string into a whole number of seconds:

- Units: `d` (86400), `h` (3600), `m` (60), `s` (1). Examples: `"90s"` -> 90, `"1h30m"` -> 5400, `"2d4h"` -> 187200.
- Units may be separated by a single space: `"1h 30m"` -> 5400. Input is case-insensitive and surrounding whitespace is ignored.
- Each unit may appear at most once, and units must be in descending order (d, h, m, s).
- Raise `ValueError` for anything else: empty string, missing unit, unknown unit, repeated or out-of-order units, negative or fractional numbers.

Keep the change inside `durations/`. Run the repository's tests before you finish.
