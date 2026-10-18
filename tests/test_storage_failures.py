"""Check storage failures preserve collection contents and graph edges."""

from __future__ import annotations

from typing import Any

import pytest

from mutrack.internal.attributes import TRACKED_MEMBERS_STORE
from mutrack.internal.object_access import raw_getattr
from mutrack.tracking.parents import get_parents_snapshot
from mutrack.tracking.state.state import MutableState
from mutrack.tracking.trackable.protocols import ITrackable
from mutrack.tracking.types import Key
from tests.helpers import (
    CountingDict,
    CountingSet,
    FailingHash,
    InputFailure,
    TrackedValue,
)


@pytest.mark.parametrize("operation", ["setitem", "setdefault"])
@pytest.mark.parametrize("preexisting", [False, True])
def test_failed_dictionary_insert_removes_only_new_edges(
    operation: str, preexisting: bool
) -> None:
    """Preserve contents and previous edges when dictionary storage fails.

    Args:
        operation: Public dictionary insertion operation under test.
        preexisting: Whether the child already has the requested edge.
    """
    values: Any = CountingDict()
    key = FailingHash(10)
    child = TrackedValue()
    if preexisting:
        values._state.link(child, key)
    before = get_parents_snapshot(child)
    key.arm(3)

    with pytest.raises(InputFailure, match="hash failed"):
        if operation == "setitem":
            values[key] = child
        else:
            values.setdefault(key, child)

    assert not values
    assert get_parents_snapshot(child) == before
    assert values.notifications == 0
    if not preexisting:
        child.changed()
        assert values.notifications == 0


def test_failed_dictionary_replacement_keeps_old_child() -> None:
    """Keep the stored child's edge when replacement storage fails."""
    key = FailingHash(10)
    old, new = TrackedValue(1), TrackedValue(2)
    values: Any = CountingDict({key: old})
    before = get_parents_snapshot(old)
    key.arm(3)

    with pytest.raises(InputFailure, match="hash failed"):
        values[key] = new

    assert values[key] is old
    assert get_parents_snapshot(old) == before
    assert not get_parents_snapshot(new)
    new.changed()
    assert values.notifications == 0
    old.changed()
    assert values.notifications == 1


@pytest.mark.parametrize("operation", ["update", "__init__"])
@pytest.mark.parametrize("prefix", [False, True])
def test_failed_dictionary_merge_keeps_only_committed_links(
    operation: str, prefix: bool
) -> None:
    """Reconcile the retained prefix and discard all speculative edges.

    Args:
        operation: Bulk mutation or silent construction entry point.
        prefix: Whether a successful replacement precedes the failing key.
    """
    key = FailingHash(10)
    old, kept = TrackedValue(1), TrackedValue(2)
    rejected, unwritten = TrackedValue(3), TrackedValue(4)
    values: Any = CountingDict({"first": old})
    incoming: dict[Any, Any] = {"first": kept} if prefix else {}
    incoming.update({key: rejected, "last": unwritten})
    key.arm(3)

    with pytest.raises(InputFailure, match="hash failed"):
        getattr(values, operation)(incoming)

    assert list(values) == ["first"]
    assert values["first"] is (kept if prefix else old)
    assert not get_parents_snapshot(rejected)
    assert not get_parents_snapshot(unwritten)
    assert (values._state in old._tracking_parents) is not prefix
    assert (values._state in kept._tracking_parents) is prefix
    if prefix:
        assert kept._tracking_parents[values._state] == {"first"}
    expected_notifications = int(prefix and operation == "update")
    assert values.notifications == expected_notifications
    rejected.changed()
    unwritten.changed()
    assert values.notifications == expected_notifications


@pytest.mark.parametrize("failure_call", [2, 3])
@pytest.mark.parametrize("preexisting", [False, True])
def test_failed_set_insert_restores_index_and_links(
    failure_call: int, preexisting: bool
) -> None:
    """Undo member bookkeeping when indexing or physical insertion fails.

    Args:
        failure_call: Hash call failing in the index or physical set write.
        preexisting: Whether to preserve a previously installed parent edge.
    """
    survivor = TrackedValue(1)
    values = CountingSet([survivor])
    member = FailingHash(2)
    if preexisting:
        values._state.link(member, None)
    before = get_parents_snapshot(member)
    member.arm(failure_call)

    with pytest.raises(InputFailure, match="hash failed"):
        values.add(member)

    assert member.hash_calls == failure_call
    assert len(values) == 1 and next(iter(values)) is survivor
    index: Any = raw_getattr(values, TRACKED_MEMBERS_STORE)
    assert list(index.values()) == [survivor]
    assert get_parents_snapshot(member) == before
    assert survivor._tracking_parents[values._state] == {None}
    assert values.notifications == 0
    if not preexisting:
        member.changed()
        assert values.notifications == 0
    survivor.changed()
    assert values.notifications == 1


def test_dictionary_rollback_continues_without_masking_storage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report cleanup errors while attempting every speculative edge removal.

    Args:
        monkeypatch: Fixture replacing one physical graph unlink operation.
    """
    values: Any = CountingDict()
    key = FailingHash(10)
    rejected, unwritten = TrackedValue(1), TrackedValue(2)
    incoming = {key: rejected, "last": unwritten}
    original_unlink = MutableState.unlink
    attempts: list[int] = []

    def failing_unlink(
        state: MutableState[ITrackable], child: ITrackable, key: Key
    ) -> bool:
        """Fail the first rollback edge and record subsequent attempts.

        Args:
            state: Parent identity token being unlinked.
            child: Speculative child whose edge should be removed.
            key: Dictionary location of the speculative edge.

        Returns:
            Whether a delegated unlink removed an edge.

        Raises:
            RuntimeError: The selected cleanup operation is unavailable.
        """
        attempts.append(id(child))
        if child is unwritten:
            raise RuntimeError("unlink failed")
        return original_unlink(state, child, key)

    monkeypatch.setattr(MutableState, "unlink", failing_unlink)
    key.arm(3)
    with pytest.raises(InputFailure, match="hash failed") as caught:
        values.update(incoming)

    assert not values
    assert attempts == [id(unwritten), id(rejected)]
    assert not rejected._tracking_parents
    assert any("unlink failed" in note for note in caught.value.__notes__)
    assert values.notifications == 0


def test_set_rollback_error_keeps_storage_failure_and_restores_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain the storage exception when physical edge cleanup also fails.

    Args:
        monkeypatch: Fixture replacing the physical graph unlink operation.
    """
    values = CountingSet()
    member = FailingHash()

    def failing_unlink(
        state: MutableState[ITrackable], child: ITrackable, key: Key
    ) -> bool:
        """Inject an unlink failure after member indexing has been restored.

        Args:
            state: Parent token whose unlink operation fails.
            child: Member whose speculative parent edge cannot be removed.
            key: Set member location, represented by None.

        Raises:
            RuntimeError: Physical graph cleanup is intentionally rejected.
        """
        raise RuntimeError("unlink failed")

    monkeypatch.setattr(MutableState, "unlink", failing_unlink)
    member.arm(3)
    with pytest.raises(InputFailure, match="hash failed") as caught:
        values.add(member)

    assert not values
    assert raw_getattr(values, TRACKED_MEMBERS_STORE) == {}
    assert any("unlink failed" in note for note in caught.value.__notes__)
    assert values.notifications == 0
