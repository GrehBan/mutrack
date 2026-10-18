"""Bridge Trackable propagation to SQLAlchemy dirty notifications."""

from __future__ import annotations

from typing import cast

from sqlalchemy.ext.mutable import Mutable

from mutrack.tracking.trackable.trackable import Trackable


class _SQLAlchemyTrackableBase(Trackable):
    """Bridge graph notifications to SQLAlchemy mutable dirty tracking."""

    def _emit_change(self) -> None:
        """Notify graph parents and mark SQLAlchemy mutable owners dirty."""
        Trackable._emit_change(self)
        Mutable.changed(cast(Mutable, self))
