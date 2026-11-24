This is a tiny static page (`index.html` + `app.js`, no build step, no dependencies) that renders a list of fruit names into `#list`.

Add a live search:

- A text input with id `q` (give it an accessible label). As the user types (the `input` event), show only the items whose text contains the typed query, case-insensitively and ignoring leading/trailing whitespace. Hide non-matching items either by not rendering them or by setting their `hidden` property. Item text must stay exactly as written in `ITEMS` (names may contain `&` and `<`; they must display literally, never be interpreted as HTML).
- An element with id `count` that always reads `N of M shown` (for example `3 of 6 shown`).
- An element with id `empty` that contains the text `No matches` and is visible only when no item matches. It must be hidden otherwise, including on first load.
- An empty query shows every item.

Verify the rendered behavior, not just the code: there is no browser test runner here, so use whatever you have available (for example a small script against the page, or a browser if present) and run the repository's tests before you finish.
