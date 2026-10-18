"""Regression tests for slices."""

from __future__ import annotations

from typing import Any

import pytest

from tests.helpers import (
    ChangingIndex,
    CountingList,
    InputFailure,
    LegacySequence,
    TrackedValue,
    failing_input,
)


@pytest.mark.parametrize(
    ("selection", "incoming"),
    [
        (slice(1, 3), [4, 5, 6]),
        (slice(None, None, 2), [4, 5]),
        (slice(None, None, -1), [4, 5, 6]),
    ],
)
def test_slice_assignment_accepts_sequence_protocol(
    selection: slice, incoming: list[int]
) -> None:
    """Verify slice assignment accepts sequence protocol.

    Args:
        selection: Slice selecting the list positions to replace.
        incoming: Values or replacement input exercised by the test.
    """
    expected = [1, 2, 3]
    actual: Any = CountingList(expected)
    expected[selection] = incoming
    actual[selection] = LegacySequence(incoming)

    assert actual == expected
    assert actual.notifications == 1


def test_sequence_protocol_links_new_children_and_unlinks_removed() -> None:
    """Verify sequence protocol links new children and unlinks removed."""
    old, new = TrackedValue(1), TrackedValue(2)
    actual: Any = CountingList([old])
    actual[:] = LegacySequence([new])

    assert not old._tracking_parents
    assert new._tracking_parents[actual._state] == {0}
    assert actual.notifications == 1


@pytest.mark.parametrize("incoming", [None, 42, LegacySequence([])])
def test_invalid_extended_slice_does_not_mutate(incoming: Any) -> None:
    """Verify invalid extended slice does not mutate.

    Args:
        incoming: Values or replacement input exercised by the test.
    """
    child = TrackedValue()
    actual: Any = CountingList([child])

    with pytest.raises((TypeError, ValueError)):
        actual[::2] = incoming

    assert actual[0] is child
    assert child._tracking_parents[actual._state] == {0}
    assert actual.notifications == 0


@pytest.mark.parametrize("delete", [False, True])
@pytest.mark.parametrize(
    ("component", "first", "later", "bounds", "size"),
    [
        (0, 0, 1, (None, 1, None), 2),
        (1, 2, 3, (None, None, None), 1),
        (2, 2, 1, (None, None, None), 2),
        (2, -1, 1, (None, None, None), 4),
        (0, 3, 2, (None, None, -2), 2),
        (1, -5, -1, (None, None, -1), 4),
        (1, -1, -5, (None, None, -1), 0),
    ],
)
def test_stateful_slice_bounds_match_native_and_keep_exact_links(
    delete: bool,
    component: int,
    first: int,
    later: int,
    bounds: tuple[int | None, int | None, int | None],
    size: int,
) -> None:
    """Resolve slice components once for storage and graph reconciliation.

    Args:
        delete: Whether to delete the slice instead of assigning it.
        component: Start, stop, or step position receiving the stateful bound.
        first: Bound used by the native operation.
        later: Different value revealing repeated conversion.
        bounds: Remaining fixed slice components.
        size: Required replacement length for the selected slice.
    """
    shared, other = TrackedValue(1), TrackedValue(2)
    incoming = TrackedValue(3)
    initial = [shared, other, shared, other]
    actual = CountingList(initial)
    expected = list(initial)
    replacements = [incoming] * size
    actual_bound, native_bound = (
        ChangingIndex(first, later),
        ChangingIndex(first, later),
    )
    actual_bounds: list[Any] = list(bounds)
    native_bounds: list[Any] = list(bounds)
    actual_bounds[component] = actual_bound
    native_bounds[component] = native_bound
    selection = slice(*actual_bounds)
    native_selection = slice(*native_bounds)

    if delete:
        del expected[native_selection]
        del actual[selection]
    else:
        expected[native_selection] = replacements
        actual[selection] = replacements

    assert actual == expected
    assert actual_bound.calls == native_bound.calls == 1
    for child in (shared, other, incoming):
        keys = {i for i, value in enumerate(actual) if value is child}
        assert child._tracking_parents.get(actual._state, set()) == keys
    assert actual.notifications == int(size != 0)


@pytest.mark.parametrize("delete", [False, True])
def test_slice_conversion_failure_keeps_contents_and_links(
    delete: bool,
) -> None:
    """Leave storage and child keys intact when a bound cannot resolve.

    Args:
        delete: Whether to exercise deletion instead of assignment.
    """

    class BrokenIndex:
        """Raise an intentional failure during slice bound conversion."""

        def __index__(self) -> int:
            """Reject conversion before any collection mutation.

            Raises:
                InputFailure: Conversion is intentionally unavailable.
            """
            raise InputFailure("index failed")

    child, incoming = TrackedValue(1), TrackedValue(2)
    actual = CountingList([child, child])
    selection = slice(BrokenIndex(), None)
    with pytest.raises(InputFailure, match="index failed"):
        if delete:
            del actual[selection]
        else:
            actual[selection] = [incoming]

    assert actual == [child, child]
    assert child._tracking_parents[actual._state] == {0, 1}
    assert not incoming._tracking_parents
    assert actual.notifications == 0


def test_failing_materialization_does_not_mutate() -> None:
    """Verify failing materialization does not mutate."""
    child = TrackedValue()
    actual = CountingList([child])

    with pytest.raises(InputFailure):
        actual[:] = failing_input(2)

    assert actual[0] is child
    assert child._tracking_parents[actual._state] == {0}
    assert actual.notifications == 0


def test_failing_sequence_access_does_not_mutate() -> None:
    """Verify failing sequence access does not mutate."""

    class FailingSequence:
        """Raise an injected failure after yielding a valid indexed prefix."""

        def __getitem__(self, index: int) -> int:
            """Return a sequence item or raise an access failure.

            Args:
                index: Integer-like position or slice selecting list
                    contents.

            Returns:
                The stored item at the requested index.

            Raises:
                InputFailure: The fixture detects sequence failed.
            """
            if index:
                raise InputFailure("sequence failed")
            return 2

    actual: Any = CountingList([1])
    with pytest.raises(InputFailure):
        actual[:] = FailingSequence()

    assert actual == [1]
    assert actual.notifications == 0
