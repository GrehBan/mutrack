"""Regression tests for sorting."""

from __future__ import annotations

import gc
import weakref
from collections.abc import Callable
from contextvars import copy_context
from typing import Any

import pytest

from mutrack.tracking.access import get_change_suppress_level
from mutrack.tracking.parents import capture_parent_links
from mutrack.tracking.suppression import batch_changes
from mutrack.tracking.trackable.trackable import Trackable
from tests.helpers import CountingList, InputFailure, TrackedValue


@pytest.mark.parametrize("initial", [[2, 1], [1]])
@pytest.mark.parametrize("operation", ["append", "extend", "__init__"])
@pytest.mark.parametrize("fail", [False, True])
def test_callback_additions_are_discarded_without_stale_links(
    initial: list[int], operation: str, fail: bool
) -> None:
    """Verify callback additions are discarded without stale links.

    Args:
        initial: Initial list values used for the native-behavior
            comparison.
        operation: Mutation callback or wrapping entry point exercised
            by the call.
        fail: Whether the callback raises the intentional test failure.

    Raises:
        InputFailure: The fixture detects key failed.
    """
    child = TrackedValue()
    actual = CountingList(initial)
    expected: list[Any] = list(initial)
    other_parent = CountingList([child])

    def key(items: list[Any], value: int) -> int:
        """Run the callback mutation or failure and return the sorting key.

        Args:
            items: List mutated by the sorting callback.
            value: Value to read, prepare, store, or compare.

        Returns:
            The key used to order the current list value.

        Raises:
            InputFailure: The fixture detects key failed.
        """
        if operation == "append":
            items.append(child)
        else:
            getattr(items, operation)([child])
        if fail:
            raise InputFailure("key failed")
        return value

    with pytest.raises((ValueError, InputFailure)) as native_error:
        expected.sort(key=lambda value: key(expected, value))
    with pytest.raises(type(native_error.value)) as tracked_error:
        actual.sort(key=lambda value: key(actual, value))

    assert tracked_error.value.args == native_error.value.args
    assert list(actual) == expected
    assert actual._state not in child._tracking_parents
    assert child._tracking_parents[other_parent._state] == {0}
    notifications = int(len(initial) >= 2 or operation != "__init__")
    assert actual.notifications == notifications
    assert get_change_suppress_level(actual) == 0
    child.changed()
    assert actual.notifications == notifications
    assert other_parent.notifications == 1


class SortValue(Trackable):
    """Invoke a configurable callback while comparing tracked sort values."""

    def __init__(self, rank: int) -> None:
        """Initialize the stored values used by this object.

        Args:
            rank: Ordering value used by callback-driven sort tests.
        """
        self.rank = rank
        self.on_compare: Callable[[], None] | None = None

    def __lt__(self, other: SortValue) -> bool:
        """Compare ranks after invoking the optional sorting callback.

        Args:
            other: Object or operand used for equality or ordering
                comparison.

        Returns:
            True when this value's rank precedes the other rank.
        """
        if self.on_compare is not None:
            self.on_compare()
        return self.rank < other.rank


@pytest.mark.parametrize("fail", [False, True])
def test_comparison_callbacks_are_reconciled(fail: bool) -> None:
    """Verify comparison callbacks are reconciled.

    Args:
        fail: Whether the callback raises the intentional test failure.

    Raises:
        InputFailure: The fixture detects comparison failed.
    """
    first, second = SortValue(2), SortValue(1)
    child = TrackedValue()
    actual = CountingList([first, second])

    def compare() -> None:
        """Mutate during comparison and optionally raise an error.

        Raises:
            InputFailure: The fixture detects comparison failed.
        """
        actual.append(child)
        if fail:
            raise InputFailure("comparison failed")

    first.on_compare = second.on_compare = compare
    with pytest.raises(InputFailure if fail else ValueError):
        actual.sort()

    assert actual._state not in child._tracking_parents
    for index, value in enumerate(actual):
        assert value._tracking_parents[actual._state] == {index}
    assert actual.notifications == 1


@pytest.mark.parametrize("duplicates", [False, True])
def test_sort_restores_links_temporarily_unlinked_by_callback(
    duplicates: bool,
) -> None:
    """Verify sort restores links temporarily unlinked by callback.

    Args:
        duplicates: Whether the initial list contains duplicate child
            identities.
    """
    first, second = TrackedValue(2), TrackedValue(1)
    initial = [first, second, first] if duplicates else [first, second]
    actual = CountingList(initial)

    def key(value: TrackedValue) -> int:
        """Run the callback mutation or failure and return the sorting key.

        Args:
            value: Value to read, prepare, store, or compare.

        Returns:
            The key used to order the current list value.
        """
        actual.append(first)
        actual.pop()
        return value.value

    with pytest.raises(ValueError):
        actual.sort(key=key)

    assert actual == sorted(initial, key=lambda value: value.value)
    for child in (first, second):
        expected_keys = {
            index for index, value in enumerate(actual) if value is child
        }
        assert child._tracking_parents[actual._state] == expected_keys
    assert actual.notifications == 1


def test_nested_sort_capture_repairs_outer_and_inner_callbacks() -> None:
    """Verify nested sort capture repairs outer and inner callbacks."""
    actual = CountingList([2, 1])
    outer_child, inner_child = TrackedValue(2), TrackedValue(1)

    def outer_key(value: int) -> int:
        """Run nested sorting callbacks and return a sorting key.

        Args:
            value: Value to read, prepare, store, or compare.

        Returns:
            The scalar key used by the outer sorting operation.
        """
        actual.append(outer_child)
        with pytest.raises(ValueError):
            actual.sort(
                key=lambda item: actual.append(inner_child) or item.value
            )
        return value

    with pytest.raises(ValueError):
        actual.sort(key=outer_key)

    assert actual == [1, 2]
    assert actual._state not in outer_child._tracking_parents
    assert actual._state not in inner_child._tracking_parents
    assert actual.notifications == 1


@pytest.mark.parametrize("initial", [[], [1], [2, 1]])
def test_normal_sort_and_notification_behavior(initial: list[int]) -> None:
    """Verify normal sort and notification behavior.

    Args:
        initial: Initial list values used for the native-behavior
            comparison.
    """
    actual = CountingList(initial)
    actual.sort()

    assert actual == sorted(initial)
    assert actual.notifications == int(len(initial) >= 2)


def test_ordinary_sort_reconciles_duplicate_child_indices() -> None:
    """Verify ordinary sort reconciles duplicate child indices."""
    first, second = TrackedValue(2), TrackedValue(1)
    actual = CountingList([first, second, first])
    actual.sort(key=lambda child: child.value)

    assert actual[0] is second
    assert first._tracking_parents[actual._state] == {1, 2}
    assert second._tracking_parents[actual._state] == {0}


def test_sort_coalesces_with_outer_notification_batch() -> None:
    """Verify sort coalesces with outer notification batch."""
    actual = CountingList([2, 1])
    child = TrackedValue()

    with batch_changes(actual):
        with pytest.raises(ValueError):
            actual.sort(key=lambda item: actual.append(child) or item)
        assert actual.notifications == 0
        actual.append(3)

    assert actual == [1, 2, 3]
    assert actual.notifications == 1
    assert actual._state not in child._tracking_parents


def test_link_capture_is_nested_and_scoped_to_parent_state() -> None:
    """Verify link capture is nested and scoped to parent state."""
    parent, other = CountingList(), CountingList()
    child = TrackedValue()
    later = TrackedValue(2)

    with capture_parent_links(parent._state) as outer:
        with capture_parent_links(parent._state) as inner:
            parent._state.link(child, 0)
            parent._state.unlink(child, 0)
            other._state.link(later, 0)
        assert outer == inner == {id(child): child}
    parent._state.link(later, 0)

    assert id(later) not in outer
    assert id(later) not in inner


def test_capture_exception_does_not_retain_children() -> None:
    """Verify capture exception does not retain children.

    Raises:
        InputFailure: The fixture detects capture failed.
    """
    parent = CountingList()
    child = TrackedValue()
    reference = weakref.ref(child)

    with pytest.raises(InputFailure):
        with capture_parent_links(parent._state):
            parent._state.link(child, 0)
            raise InputFailure("capture failed")
    del child
    gc.collect()

    assert reference() is None


def test_copied_context_does_not_keep_closed_capture_active() -> None:
    """Verify copied context does not keep closed capture active."""
    parent = CountingList()
    child = TrackedValue()
    later = TrackedValue(2)
    reference = weakref.ref(child)

    with capture_parent_links(parent._state) as captured:
        context = copy_context()
        parent._state.link(child, 0)

    context.run(parent._state.link, later, 0)
    assert id(later) not in captured
    del child, captured
    gc.collect()

    assert reference() is None
