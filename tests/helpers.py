"""Provide helpers used by the regression suite."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from mutrack.adapters.sqlalchemy.collections.dict import (
    SQLAlchemyTrackableDict,
)
from mutrack.adapters.sqlalchemy.collections.list import (
    SQLAlchemyTrackableList,
)
from mutrack.adapters.sqlalchemy.collections.set import SQLAlchemyTrackableSet
from mutrack.tracking.trackable.trackable import Trackable


class CountingList(SQLAlchemyTrackableList[Any]):
    """Count tracked list notifications in regression tests."""

    notifications = 0

    def _emit_change(self) -> None:
        """Propagate a change to live parents."""
        self.notifications += 1
        super()._emit_change()


class CountingDict(SQLAlchemyTrackableDict[str, Any]):
    """Count tracked dictionary notifications in tests."""

    notifications = 0

    def _emit_change(self) -> None:
        """Propagate a change to live parents."""
        self.notifications += 1
        super()._emit_change()


class CountingSet(SQLAlchemyTrackableSet[Any]):
    """Count tracked set notifications in regression tests."""

    notifications = 0

    def _emit_change(self) -> None:
        """Propagate a change to live parents."""
        self.notifications += 1
        super()._emit_change()


class PlainValue:
    """Provide hash and equality semantics for set link tests."""

    def __init__(self, value: int = 1) -> None:
        """Initialize the stored values used by this object.

        Args:
            value: Value to read, prepare, store, or compare.
        """
        self.value = value

    def __hash__(self) -> int:
        """Hash the comparison value used by equal-member regression tests.

        Returns:
            The hash of the test value used for set membership.
        """
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        """Compare values using the set test equality rules.

        Args:
            other: Object or operand used for equality or ordering
                comparison.

        Returns:
            True when the comparison operand has an equal logical
            value.
        """
        return isinstance(other, PlainValue) and self.value == other.value


class TrackedValue(PlainValue, Trackable):
    """Combine comparable test values with Trackable change propagation."""

    def __getstate__(self) -> dict[str, int]:
        """Serialize logical state without tracking internals.

        Returns:
            Only the serializable logical state of the test value.
        """
        return {"value": self.value}

    def __setstate__(self, state: dict[str, int]) -> None:
        """Restore logical state from a serialized mapping.

        Args:
            state: Parent identity token or serialized state mapping.
        """
        self.value = state["value"]


class InputFailure(RuntimeError):
    """Identify intentional iterator and callback test failures."""

    pass


class FailingHash(TrackedValue):
    """Raise once at a selected hash call while retaining stable equality."""

    hash_calls = 0
    fail_hash_at: int | None = None

    def arm(self, call: int) -> None:
        """Restart hash counting and select the failing call.

        Args:
            call: One-based hash call that raises the test failure.
        """
        self.hash_calls = 0
        self.fail_hash_at = call

    def __hash__(self) -> int:
        """Hash the logical value unless this is the selected failure call.

        Returns:
            A stable hash of the logical test value.

        Raises:
            InputFailure: The armed hash call is reached.
        """
        self.hash_calls += 1
        if self.hash_calls == self.fail_hash_at:
            raise InputFailure("hash failed")
        return hash(self.value)


class ChangingIndex:
    """Return a different integer if an operation resolves an index twice."""

    def __init__(self, first: int, later: int) -> None:
        """Store the first and subsequent conversion results.

        Args:
            first: Integer returned by the first conversion.
            later: Integer returned by every later conversion.
        """
        self.first = first
        self.later = later
        self.calls = 0

    def __index__(self) -> int:
        """Return the result for this invocation and count the conversion.

        Returns:
            The first result once, then the subsequent result.
        """
        self.calls += 1
        return self.first if self.calls == 1 else self.later


class LegacySequence:
    """Expose integer-index sequence iteration without an __iter__ method."""

    def __init__(self, values: list[Any]) -> None:
        """Initialize the stored values used by this object.

        Args:
            values: Incoming values processed by the operation.
        """
        self.values = values

    def __getitem__(self, index: int) -> Any:
        """Return a sequence item or raise an access failure.

        Args:
            index: Integer-like position or slice selecting list
                contents.

        Returns:
            The stored item at the requested index.
        """
        return self.values[index]


def failing_input(*values: Any) -> Iterator[Any]:
    """Yield the supplied prefix, then raise the injected iterator failure.

    Args:
        *values: Incoming values processed by the operation.

    Yields:
        Each supplied value before the injected failure is raised.

    Raises:
        InputFailure: The fixture detects input failed.
    """
    yield from values
    raise InputFailure("input failed")
