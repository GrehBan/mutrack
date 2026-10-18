"""Provide adapters.sqlalchemy.collections.base for mutation tracking."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeVar, cast

from mutrack.adapters.sqlalchemy.base import _SQLAlchemyTrackableBase
from mutrack.adapters.sqlalchemy.collections.registry import (
    get_sqlalchemy_containers,
)
from mutrack.tracking.runtime import prepare_runtime_values
from mutrack.tracking.wrapping import (
    prepare_value,
    prepare_values,
    validate_values,
)

V = TypeVar("V")


class _SQLAlchemyTrackableCollection(_SQLAlchemyTrackableBase):
    """Shared helpers for SQLAlchemy trackable containers.

    Values are converted with ``prepare_value`` / ``prepare_values``:
    plain containers become trackable wrappers, but the returned roots
    are NOT linked to this collection. Callers link them under their
    final keys.

    Preparation is type-preserving (a ``list`` becomes a ``list``
    subclass, and so on), so the helpers are typed as returning their
    input type.
    """

    def _prepare_value(
        self,
        value: V,
        /,
    ) -> V:
        """Wrap a new value without linking its root to this collection.

        Args:
            value: Value to read, prepare, store, or compare.

        Returns:
            The prepared value without an external parent link.
        """
        validate_values(self, (value,))
        prepared = prepare_runtime_values(self, (value,))
        if prepared is not None:
            return cast(V, prepared[0])

        return cast(
            V,
            prepare_value(
                value,
                containers=get_sqlalchemy_containers(),
                max_depth=self._max_depth_limit,
            ),
        )

    def _prepare_values(
        self,
        values: Iterable[V],
        /,
    ) -> list[V]:
        """Prepare values together to preserve shared references.

        Args:
            values: Incoming values processed by the operation.

        Returns:
            Prepared values preserving aliases across the input
            sequence.
        """
        materialized = list(values)
        validate_values(self, materialized)
        prepared = prepare_runtime_values(self, materialized)
        if prepared is not None:
            return cast("list[V]", prepared)

        return cast(
            "list[V]",
            prepare_values(
                materialized,
                containers=get_sqlalchemy_containers(),
                max_depth=self._max_depth_limit,
            ),
        )
