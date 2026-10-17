from __future__ import annotations

from sqlalchemy.ext.mutable import Mutable

from mutrack.tracking.trackable.trackable import Trackable


class SQLAlchemyTrackable(Trackable, Mutable):
    """Bridge between mutrack tracking and SQLAlchemy Mutable."""

    def _emit_change(self) -> None:
        Trackable._emit_change(self)
        Mutable.changed(self)