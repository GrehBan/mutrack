"""Regression tests for sets."""

from __future__ import annotations

import pytest

from tests.helpers import (
    CountingSet,
    InputFailure,
    PlainValue,
    TrackedValue,
    failing_input,
)


@pytest.mark.parametrize("operation", ["construct", "update", "__init__"])
@pytest.mark.parametrize("tracked_first", [False, True])
def test_set_links_only_first_equal_representative(
    operation: str, tracked_first: bool
) -> None:
    """Verify set links only first equal representative.

    Args:
        operation: Mutation callback or wrapping entry point exercised
            by the call.
        tracked_first: Whether the Trackable is the first equal
            incoming representative.
    """
    plain, tracked = PlainValue(), TrackedValue()
    incoming = [tracked, plain] if tracked_first else [plain, tracked]
    values = CountingSet()

    if operation == "construct":
        values = CountingSet(incoming)
    else:
        getattr(values, operation)(incoming)

    assert len(values) == 1
    assert next(iter(values)) is incoming[0]
    assert (values._state in tracked._tracking_parents) is tracked_first
    before = values.notifications
    tracked.changed()
    assert values.notifications == before + int(tracked_first)


def test_existing_plain_member_prevents_linking_equal_trackable() -> None:
    """Verify existing plain member prevents linking equal trackable."""
    plain, tracked = PlainValue(), TrackedValue()
    values = CountingSet([plain])
    values.update([tracked])

    assert next(iter(values)) is plain
    assert not tracked._tracking_parents
    assert values.notifications == 0


def test_equal_trackables_link_only_stored_identity() -> None:
    """Verify equal trackables link only stored identity."""
    first, second = TrackedValue(), TrackedValue()
    values = CountingSet([first, second])
    values.update([second])

    assert next(iter(values)) is first
    assert values._state in first._tracking_parents
    assert not second._tracking_parents
    values.remove(second)
    assert not first._tracking_parents
    assert not values


def test_reinitialization_replaces_equal_representative_and_links() -> None:
    """Verify reinitialization replaces equal representative and links."""
    first, second = TrackedValue(), TrackedValue()
    values = CountingSet([first])
    values.__init__([second])

    assert next(iter(values)) is second
    assert not first._tracking_parents
    assert values._state in second._tracking_parents
    assert values.notifications == 0


def test_reinitialization_keeps_shared_member_link() -> None:
    """Verify reinitialization keeps shared member link."""
    child = TrackedValue()
    values = CountingSet([child])
    values.__init__([child])

    assert values._state in child._tracking_parents
    values.pop()
    assert not child._tracking_parents


@pytest.mark.parametrize("remove_first", [False, True])
def test_partial_difference_failure_repairs_links_and_notifies(
    remove_first: bool,
) -> None:
    """Verify partial difference failure repairs links and notifies.

    Args:
        remove_first: Whether the failing iterator removes a member
            before raising.
    """
    removed, retained = TrackedValue(1), TrackedValue(2)
    values = CountingSet([removed, retained])
    incoming = failing_input(removed) if remove_first else failing_input()

    with pytest.raises(InputFailure, match="input failed"):
        values.difference_update(incoming)

    assert (removed in values) is not remove_first
    assert (values._state in removed._tracking_parents) is not remove_first
    assert values._state in retained._tracking_parents
    assert values.notifications == int(remove_first)
    removed.changed()
    assert values.notifications == 1


def test_difference_failure_in_later_argument_preserves_earlier_removal() -> (
    None
):
    """Verify earlier removals survive a later input failure."""
    child = TrackedValue()
    values = CountingSet([child, 2])

    with pytest.raises(InputFailure):
        values.difference_update([child], failing_input())

    assert values == {2}
    assert not child._tracking_parents
    assert values.notifications == 1


def test_difference_noop_and_successful_removal() -> None:
    """Verify difference noop and successful removal."""
    child = TrackedValue()
    values = CountingSet([child, 2])
    values.difference_update([99])
    assert values.notifications == 0
    values.difference_update([child], [2])
    assert not values
    assert not child._tracking_parents
    assert values.notifications == 1


def test_difference_in_place_operator_keeps_links_consistent() -> None:
    """Verify difference in place operator keeps links consistent."""
    child = TrackedValue()
    values = CountingSet([child, 2])
    original = values
    values -= {child}

    assert values is original
    assert values == {2}
    assert not child._tracking_parents
    assert original.notifications == 1


@pytest.mark.parametrize("tracked_first", [False, True])
def test_failed_update_preserves_prefix_without_linking_nonmembers(
    tracked_first: bool,
) -> None:
    """Verify failed update preserves prefix without linking nonmembers.

    Args:
        tracked_first: Whether the Trackable is the first equal
            incoming representative.
    """
    plain, tracked = PlainValue(), TrackedValue()
    incoming = [tracked, plain, []] if tracked_first else [plain, tracked, []]
    values = CountingSet()
    expected: set[object] = set()

    with pytest.raises(TypeError):
        expected.update(incoming)
    with pytest.raises(TypeError):
        values.update(incoming)

    assert values == expected
    assert next(iter(values)) is incoming[0]
    assert (values._state in tracked._tracking_parents) is tracked_first
    assert values.notifications == 1


def test_failed_update_before_addition_does_not_notify() -> None:
    """Verify failed update before addition does not notify."""
    values = CountingSet([1])

    with pytest.raises(TypeError):
        values.update([[]])

    assert values == {1}
    assert values.notifications == 0
