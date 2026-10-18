"""Provide the cached SQLAlchemy wrapper types to explicit callers."""

from __future__ import annotations

from functools import cache

from mutrack.tracking.wrapping import ContainerTypes


@cache
def get_sqlalchemy_containers() -> ContainerTypes:
    """Return the cached SQLAlchemy Trackable container implementations.

    Returns:
        A cached registry containing the SQLAlchemy wrapper classes.
    """
    from mutrack.adapters.sqlalchemy.collections.dict import (
        SQLAlchemyTrackableDict,
    )
    from mutrack.adapters.sqlalchemy.collections.list import (
        SQLAlchemyTrackableList,
    )
    from mutrack.adapters.sqlalchemy.collections.set import (
        SQLAlchemyTrackableSet,
    )

    return ContainerTypes(
        list_type=SQLAlchemyTrackableList,
        dict_type=SQLAlchemyTrackableDict,
        set_type=SQLAlchemyTrackableSet,
    )
