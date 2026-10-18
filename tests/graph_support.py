"""Provide graph support used by the regression suite."""

from __future__ import annotations

from typing import Any, ClassVar

from mutrack.tracking.trackable.protocols import is_trackable
from mutrack.tracking.trackable.trackable import Trackable
from mutrack.tracking.wrapping import ContainerTypes


class Model(Trackable):
    """Store dynamic test fields and record graph change propagation.

    Attributes:
        events: Emitted object identities recorded by the test fixture.
    """

    events: ClassVar[list[int]] = []

    def __init__(self, **values: Any) -> None:
        """Initialize the stored values used by this object.

        Args:
            **values: Incoming values processed by the operation.
        """
        for name, value in values.items():
            object.__setattr__(self, name, value)

    def __getattr__(self, name: str) -> Any:
        """Read a dynamically named stored attribute for a test model.

        Args:
            name: Stored attribute or declared field name.

        Returns:
            The dynamically named stored test attribute.
        """
        return object.__getattribute__(self, name)

    def _emit_change(self) -> None:
        """Propagate a change to live parents."""
        self.events.append(id(self))
        super()._emit_change()


class NeutralList(Trackable, list[Any]):
    """Provide a minimal ORM-free Trackable list for graph-building tests."""

    def append(self, value: Any) -> None:
        """Append a value, link its final index, and notify.

        Args:
            value: Value to read, prepare, store, or compare.
        """
        if is_trackable(value):
            self._state.link(value, len(self))
        list.append(self, value)
        self.changed()


class NeutralDict(Trackable, dict[Any, Any]):
    """Provide an ORM-free Trackable dictionary for graph tests."""

    def __setitem__(self, key: Any, value: Any) -> None:
        """Store replacement values while keeping child links consistent.

        Args:
            key: Field name, container key, list index, or None for a
                set member.
            value: Value to read, prepare, store, or compare.
        """
        if is_trackable(value):
            self._state.link(value, key)
        dict.__setitem__(self, key, value)
        self.changed()


class NeutralSet(Trackable, set[Any]):
    """Provide a minimal ORM-free Trackable set for graph-building tests."""

    def add(self, value: Any) -> None:
        """Add a new set member and link it before emitting a notification.

        Args:
            value: Value to read, prepare, store, or compare.
        """
        if is_trackable(value):
            self._state.link(value, None)
        set.add(self, value)
        self.changed()


CONTAINERS = ContainerTypes(
    list_type=NeutralList, dict_type=NeutralDict, set_type=NeutralSet
)
