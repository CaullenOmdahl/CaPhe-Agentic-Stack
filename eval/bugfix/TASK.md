Bug report: the `paginate` function in `pager/paginate.py` returns the wrong items on some pages. For example, requesting the last page of a list whose length is not a multiple of the page size loses or misplaces items, and the reported `total_pages` is sometimes wrong.

Find the root cause and fix it with a minimal change. Do not change the function's signature or return shape. Add or update a test that covers the bug. Run the repository's tests before you finish.
