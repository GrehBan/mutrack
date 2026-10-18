"""Expose model mutation tracking through SQLAlchemy Mutable."""

from __future__ import annotations

from sqlalchemy.ext.mutable import Mutable

from mutrack.adapters.sqlalchemy.base import _SQLAlchemyTrackableBase


class SQLAlchemyTrackable(_SQLAlchemyTrackableBase, Mutable):
    """Expose the mutation graph through SQLAlchemy Mutable integration."""

    pass
