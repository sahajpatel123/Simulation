"""
Drop into any endpoint or task to count DB queries.
Usage:
    with QueryCounter(db) as counter:
        ... do DB work ...
    print(f"Queries: {counter.count}")
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session


class QueryCounter:
    def __init__(self, session: Session):
        self.session = session
        self.count = 0
        self._before: Any = None
        self._bind: Any = None

    def __enter__(self) -> QueryCounter:
        bind = self.session.get_bind()
        if bind is None:
            return self

        def before_cursor_execute(
            conn, cursor, statement, parameters, context, executemany
        ) -> None:
            self.count += 1

        event.listen(bind, "before_cursor_execute", before_cursor_execute)
        self._before = before_cursor_execute
        self._bind = bind
        return self

    def __exit__(self, *args: object) -> None:
        if self._bind is not None and self._before is not None:
            event.remove(self._bind, "before_cursor_execute", self._before)
        self._before = None
        self._bind = None
