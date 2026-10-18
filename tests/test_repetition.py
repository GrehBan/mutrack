"""Regression tests for repetition."""

from __future__ import annotations

import sys

import pytest

from mutrack.tracking.parents import get_parents_snapshot
from mutrack.tracking.trackable.protocols import ITrackable
from mutrack.tracking.types import Key
from tests.helpers import CountingList, InputFailure, TrackedValue


@pytest.mark.parametrize(
    "count", [10**100, -(10**100), sys.maxsize + 1, -sys.maxsize - 2]
)
@pytest.mark.parametrize("kind", ["empty", "scalar", "tracked"])
def test_out_of_range_repeat_matches_native_without_mutation(
    count: int, kind: str
) -> None:
    """Verify out of range repeat matches native without mutation.

    Args:
        count: Repetition count exercised by the test.
        kind: Container or model variant selected for the test.
    """
    child = TrackedValue()
    initial = [] if kind == "empty" else [child if kind == "tracked" else 1]
    actual = CountingList(initial)
    before = get_parents_snapshot(child)
    expected = list(initial)

    with pytest.raises(OverflowError):
        expected *= count
    with pytest.raises(OverflowError):
        actual.__imul__(count)

    assert actual == expected == initial
    assert get_parents_snapshot(child) == before
    assert actual.notifications == 0


@pytest.mark.parametrize("count", [sys.maxsize, -sys.maxsize - 1])
def test_valid_index_boundaries_on_empty_list(count: int) -> None:
    """Verify valid index boundaries on empty list.

    Args:
        count: Repetition count exercised by the test.
    """
    actual = CountingList()

    assert actual.__imul__(count) is actual
    assert actual == []
    assert actual.notifications == 0


@pytest.mark.parametrize("count", [-sys.maxsize - 1, -1, 0, 1, 3, False, True])
def test_valid_repeat_preserves_aliases_and_exact_parent_keys(
    count: int,
) -> None:
    """Verify valid repeat preserves aliases and exact parent keys.

    Args:
        count: Repetition count exercised by the test.
    """
    child = TrackedValue()
    initial = [child, 1, child]
    actual = CountingList(initial)

    assert actual.__imul__(count) is actual
    assert actual == initial * count
    expected_keys = {
        index for index, value in enumerate(actual) if value is child
    }
    assert child._tracking_parents.get(actual._state, set()) == expected_keys
    assert actual.notifications == int(count != 1)


@pytest.mark.parametrize("kind", ["scalar", "tracked"])
def test_native_size_overflow_fails_before_expanding_links(kind: str) -> None:
    """Verify native size overflow fails before expanding links.

    Args:
        kind: Container or model variant selected for the test.
    """
    child = TrackedValue()
    actual = CountingList([child, child] if kind == "tracked" else [1, 2])
    before = get_parents_snapshot(child)
    initial = list(actual)

    with pytest.raises(MemoryError):
        actual.__imul__(sys.maxsize)

    assert actual == initial
    assert get_parents_snapshot(child) == before
    assert actual.notifications == 0


@pytest.mark.parametrize("count", [3, sys.maxsize + 1])
def test_index_protocol_is_called_exactly_once(count: int) -> None:
    """Verify index protocol is called exactly once.

    Args:
        count: Repetition count exercised by the test.
    """

    class Index:
        """Supply index conversion for list repetition tests."""

        calls = 0

        def __index__(self) -> int:
            """Return the repetition count or raise a test failure.

            Returns:
                The integer count supplied by the index fixture.
            """
            self.calls += 1
            return count

    index = Index()
    actual = CountingList([1])
    if count > sys.maxsize:
        with pytest.raises(OverflowError):
            actual.__imul__(index)
        assert actual == [1]
    else:
        assert actual.__imul__(index) == [1, 1, 1]

    assert index.calls == 1


def test_index_exception_does_not_mutate() -> None:
    """Verify index exception does not mutate."""

    class Index:
        """Supply index conversion for list repetition tests."""

        def __index__(self) -> int:
            """Return the repetition count or raise a test failure.

            Returns:
                The integer count supplied by the index fixture.

            Raises:
                InputFailure: The fixture detects index failed.
            """
            raise InputFailure("index failed")

    actual = CountingList([1])
    with pytest.raises(InputFailure):
        actual.__imul__(Index())

    assert actual == [1]
    assert actual.notifications == 0


def test_linking_failure_restores_storage_and_original_alias_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify linking failure restores storage and original alias links.

    Args:
        monkeypatch: Pytest fixture that restores temporary method
            replacements.

    Raises:
        InputFailure: The fixture detects link failed.
    """
    child = TrackedValue()
    actual = CountingList([child, child])
    state = actual._state
    link = state.link
    before = get_parents_snapshot(child)

    def fail_on_second_new_key(value: ITrackable, key: Key) -> bool:
        """Fail after one repeated child link has already been created.

        Args:
            value: Value to read, prepare, store, or compare.
            key: Field name, container key, list index, or None for a
                set member.

        Returns:
            Whether the delegated repetition link was created.

        Raises:
            InputFailure: The fixture detects link failed.
        """
        if key == 3:
            raise InputFailure("link failed")
        return link(value, key)

    monkeypatch.setattr(state, "link", fail_on_second_new_key)
    with pytest.raises(InputFailure, match="link failed"):
        actual.__imul__(3)

    assert len(actual) == 2
    assert actual[0] is actual[1] is child
    assert get_parents_snapshot(child) == before
    assert actual.notifications == 0
