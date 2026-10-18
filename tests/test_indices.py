"""Check list index conversion and native signed index limits."""

from __future__ import annotations

import operator
import sys

import pytest

from mutrack.tracking.parents import get_parents_snapshot
from tests.helpers import ChangingIndex, CountingList, TrackedValue


@pytest.mark.parametrize("operation", ["insert", "pop"])
@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize(
    "index", [2**100, -(2**100), sys.maxsize + 1, -sys.maxsize - 2]
)
def test_oversized_indices_match_native_without_mutation(
    operation: str, empty: bool, index: int
) -> None:
    """Reject oversized positions before modifying contents or graph links.

    Args:
        operation: Native-sized insertion or removal operation.
        empty: Whether the starting list has no items.
        index: Integer outside the native signed index range.
    """
    child, incoming = TrackedValue(1), TrackedValue(2)
    initial = [] if empty else [child]
    actual = CountingList(initial)
    expected = list(initial)
    before = get_parents_snapshot(child)
    args = (index, incoming) if operation == "insert" else (index,)

    with pytest.raises(OverflowError):
        getattr(expected, operation)(*args)
    with pytest.raises(OverflowError):
        getattr(actual, operation)(*args)

    assert actual == expected == initial
    assert get_parents_snapshot(child) == before
    assert not incoming._tracking_parents
    assert actual.notifications == 0


@pytest.mark.parametrize("index", [sys.maxsize, -sys.maxsize - 1])
def test_native_boundary_insertion_clamps_and_links(index: int) -> None:
    """Accept native boundary indices and clamp them like built-in lists.

    Args:
        index: Smallest or largest permitted native signed integer.
    """
    child, incoming = TrackedValue(1), TrackedValue(2)
    actual = CountingList([child])
    expected = [child]
    expected.insert(index, incoming)
    actual.insert(index, incoming)

    assert actual == expected
    for position, item in enumerate(actual):
        assert item._tracking_parents[actual._state] == {position}
    assert actual.notifications == 1


@pytest.mark.parametrize("index", [sys.maxsize, -sys.maxsize - 1])
def test_native_boundary_pop_raises_index_error(index: int) -> None:
    """Distinguish valid native indices from positions beyond the list.

    Args:
        index: Valid native integer outside this list's populated positions.
    """
    actual = CountingList([1])
    with pytest.raises(IndexError):
        [1].pop(index)
    with pytest.raises(IndexError):
        actual.pop(index)
    assert actual == [1]
    assert actual.notifications == 0


@pytest.mark.parametrize("operation", ["insert", "pop"])
def test_single_index_conversion_matches_native(operation: str) -> None:
    """Resolve each insertion or pop index exactly once.

    Args:
        operation: Public list operation consuming an integer-like position.
    """
    child, incoming = TrackedValue(1), TrackedValue(2)
    actual = CountingList([child])
    expected = [child]
    actual_index, native_index = ChangingIndex(0, 1), ChangingIndex(0, 1)
    actual_args = (
        (actual_index, incoming) if operation == "insert" else (actual_index,)
    )
    native_args = (
        (native_index, incoming) if operation == "insert" else (native_index,)
    )
    getattr(expected, operation)(*native_args)
    getattr(actual, operation)(*actual_args)

    assert actual == expected
    assert actual_index.calls == native_index.calls == 1
    for item in (child, incoming):
        keys = {i for i, value in enumerate(actual) if value is item}
        assert item._tracking_parents.get(actual._state, set()) == keys
    assert actual.notifications == 1


@pytest.mark.parametrize("operation", ["getitem", "setitem", "delitem"])
def test_oversized_subscription_still_raises_index_error(
    operation: str,
) -> None:
    """Retain subscription errors that differ from insert and pop errors.

    Args:
        operation: Subscription operation whose index failure is checked.
    """
    child, incoming = TrackedValue(1), TrackedValue(2)
    actual = CountingList([child])
    args = (2**100, incoming) if operation == "setitem" else (2**100,)
    with pytest.raises(IndexError):
        getattr(operator, operation)([child], *args)
    with pytest.raises(IndexError):
        getattr(operator, operation)(actual, *args)
    assert actual == [child]
    assert child._tracking_parents[actual._state] == {0}
    assert not incoming._tracking_parents
    assert actual.notifications == 0


def test_insert_resolves_overflow_before_preparing_incoming_value() -> None:
    """Reject an oversized index before validating a cycle-forming value."""
    actual = CountingList([1])
    with pytest.raises(OverflowError):
        actual.insert(2**100, actual)
    assert actual == [1]
    assert not actual._tracking_parents
    assert actual.notifications == 0


@pytest.mark.parametrize("operation", ["insert", "pop"])
@pytest.mark.parametrize("empty", [False, True])
def test_oversized_index_object_is_resolved_once(
    operation: str, empty: bool
) -> None:
    """Raise overflow before inspecting emptiness or converting an index twice.

    Args:
        operation: Native-sized insertion or removal operation.
        empty: Whether to begin with an empty list.
    """
    actual = CountingList([] if empty else [1])
    expected = list(actual)
    actual_index = ChangingIndex(sys.maxsize + 1, 0)
    native_index = ChangingIndex(sys.maxsize + 1, 0)
    actual_args = (
        (actual_index, 2) if operation == "insert" else (actual_index,)
    )
    native_args = (
        (native_index, 2) if operation == "insert" else (native_index,)
    )

    with pytest.raises(OverflowError):
        getattr(expected, operation)(*native_args)
    with pytest.raises(OverflowError):
        getattr(actual, operation)(*actual_args)

    assert actual == expected
    assert actual_index.calls == native_index.calls == 1
    assert actual.notifications == 0
