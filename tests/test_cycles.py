"""Regression tests for cycles."""

from __future__ import annotations

import gc
import operator
import weakref
from collections.abc import Callable
from typing import Any

import pytest

from mutrack.adapters.sqlalchemy.collections.registry import (
    get_sqlalchemy_containers,
)
from mutrack.tracking.graph.linking.collections import (
    link_childrens,
    link_entries,
    reconcile_child_links,
    snapshot_sequence_links,
)
from mutrack.tracking.parents import get_parents_snapshot
from mutrack.tracking.wrapping import wrap_value
from tests.helpers import CountingDict, CountingList, CountingSet, TrackedValue


@pytest.mark.parametrize(
    "mutate",
    [
        lambda obj, value: obj.append(value),
        lambda obj, value: obj.extend([value]),
        lambda obj, value: obj.insert(0, value),
        lambda obj, value: operator.setitem(obj, 0, value),
        lambda obj, value: operator.setitem(obj, slice(None), [value]),
        lambda obj, value: operator.setitem(
            obj, slice(None, None, 2), [value]
        ),
        lambda obj, value: obj.__init__([value]),
        lambda obj, value: operator.iadd(obj, [value]),
    ],
)
@pytest.mark.parametrize("nested", [False, True])
def test_list_rejects_cycles_without_mutation(
    mutate: Callable[[Any, Any], Any], nested: bool
) -> None:
    """Verify list rejects cycles without mutation.

    Args:
        mutate: Mutation operation applied to the proposed child
            reference.
        nested: Whether the proposed reference is nested inside plain
            containers.
    """
    child = TrackedValue()
    values = CountingList([child])
    before = get_parents_snapshot(child)
    incoming = {"nested": [values]} if nested else values

    with pytest.raises(ValueError, match="cyclic"):
        mutate(values, incoming)

    assert len(values) == 1 and values[0] is child
    assert get_parents_snapshot(child) == before
    assert not get_parents_snapshot(values)
    assert values.notifications == 0
    child.changed()
    assert values.notifications == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda obj, value: operator.setitem(obj, "new", value),
        lambda obj, value: obj.setdefault("new", value),
        lambda obj, value: obj.update({"new": value}),
        lambda obj, value: obj.__init__({"new": value}),
        lambda obj, value: operator.ior(obj, {"new": value}),
    ],
)
def test_dictionary_rejects_mixed_ancestor_cycles(
    mutate: Callable[[Any, Any], Any],
) -> None:
    """Verify dictionary rejects mixed ancestor cycles.

    Args:
        mutate: Mutation operation applied to the proposed child
            reference.
    """
    child = CountingDict({"old": 1})
    root = CountingList([child])
    before = get_parents_snapshot(child)

    with pytest.raises(ValueError, match="cyclic"):
        mutate(child, {"wrapped": [root]})

    assert child == {"old": 1}
    assert get_parents_snapshot(child) == before
    assert not get_parents_snapshot(root)
    assert child.notifications == root.notifications == 0


def test_deep_cycle_and_valid_aliasing() -> None:
    """Verify deep cycle and valid aliasing."""
    leaf = CountingList()
    middle = CountingDict({"leaf": leaf})
    root = CountingList([middle, leaf])
    root.append(leaf)
    root.notifications = 0

    with pytest.raises(ValueError, match="cyclic"):
        leaf.append(root)

    assert not leaf
    leaf.append(1)
    assert root.notifications > 0
    assert leaf._tracking_parents[root._state] == {1, 2}
    assert leaf._tracking_parents[middle._state] == {"leaf"}


def test_batch_rejection_does_not_leave_links_or_wrappers() -> None:
    """Verify batch rejection does not leave links or wrappers."""
    root = CountingList()
    child = TrackedValue()

    with pytest.raises(ValueError, match="cyclic"):
        root.extend([[child], root])

    assert not root
    assert not get_parents_snapshot(child)
    assert not get_parents_snapshot(root)
    assert root.notifications == 0


def test_link_entries_rolls_back_new_edges_only() -> None:
    """Verify link entries rolls back new edges only."""
    parent = CountingList()
    child = TrackedValue()
    parent._state.link(child, 4)

    with pytest.raises(ValueError, match="cyclic"):
        link_entries(parent, [(4, child), (5, child), (6, parent)])

    assert child._tracking_parents[parent._state] == {4}
    assert not get_parents_snapshot(parent)


def test_direct_state_link_rejects_cycle() -> None:
    """Verify direct state link rejects cycle."""
    parent, child = CountingList(), CountingList()
    parent._state.link(child, 0)

    with pytest.raises(ValueError, match="cyclic"):
        child._state.link(parent, 0)

    assert not get_parents_snapshot(parent)


def test_wrap_value_rejection_rolls_back_entire_graph() -> None:
    """Verify wrap value rejection rolls back entire graph."""
    root = CountingList()
    child = TrackedValue()

    with pytest.raises(ValueError, match="cyclic"):
        wrap_value(
            root,
            [child, root],
            0,
            containers=get_sqlalchemy_containers(),
        )

    assert not get_parents_snapshot(child)
    assert not get_parents_snapshot(root)


def test_plain_container_cycle_still_rejected() -> None:
    """Verify plain container cycle still rejected."""
    cyclic: list[Any] = []
    cyclic.append(cyclic)
    parent = CountingList()

    with pytest.raises(ValueError, match="cyclic"):
        parent.append(cyclic)

    assert not parent
    assert parent.notifications == 0


@pytest.mark.parametrize("operation", ["add", "update", "__init__"])
def test_set_rejects_ancestor_without_losing_existing_links(
    operation: str,
) -> None:
    """Verify set rejects ancestor without losing existing links.

    Args:
        operation: Mutation callback or wrapping entry point exercised
            by the call.
    """
    values = CountingSet([TrackedValue(1)])
    ancestor = TrackedValue(2)
    ancestor._state.link(values, None)
    old = next(iter(values))

    with pytest.raises(ValueError, match="cyclic"):
        if operation == "add":
            values.add(ancestor)
        else:
            getattr(values, operation)([ancestor])

    assert len(values) == 1 and next(iter(values)) is old
    assert values._state in old._tracking_parents
    assert not get_parents_snapshot(ancestor)
    assert values.notifications == 0


def test_parent_links_remain_weak() -> None:
    """Verify parent links remain weak."""
    child = TrackedValue()
    parent = CountingList([child])
    reference = weakref.ref(parent)
    del parent
    gc.collect()

    assert reference() is None
    assert not get_parents_snapshot(child)


def test_bulk_child_linking_rolls_back_on_cycle() -> None:
    """Verify bulk child linking rolls back on cycle."""
    parent = CountingList()
    child = TrackedValue()

    list.extend(parent, [child, parent])

    with pytest.raises(ValueError, match="cyclic"):
        link_childrens(parent)

    assert not child._tracking_parents
    assert not parent._tracking_parents


def test_reconciliation_validates_before_removing_existing_links() -> None:
    """Verify reconciliation validates before removing existing links."""
    old, new = TrackedValue(1), TrackedValue(2)
    parent = CountingList([old])

    with pytest.raises(ValueError, match="cyclic"):
        reconcile_child_links(
            parent,
            snapshot_sequence_links([old]),
            snapshot_sequence_links([new, parent]),
        )

    assert old._tracking_parents[parent._state] == {0}
    assert not new._tracking_parents
    assert not parent._tracking_parents


def test_cycle_detection_does_not_use_python_recursion() -> None:
    """Verify cycle detection does not use python recursion."""
    nodes = [TrackedValue(index) for index in range(1100)]
    for parent, child in zip(nodes, nodes[1:]):
        parent._state.link(child, None)

    with pytest.raises(ValueError, match="cyclic"):
        nodes[-1]._state.link(nodes[0], None)

    assert not nodes[0]._tracking_parents


def test_acyclic_shared_plain_containers_keep_identity() -> None:
    """Verify acyclic shared plain containers keep identity."""
    shared: list[int] = []
    parent = CountingList([shared, {"shared": shared}])

    assert parent[0] is parent[1]["shared"]
    parent[0].append(1)
    assert parent[1]["shared"] == [1]


def test_expired_state_is_ignored_by_cycle_detection() -> None:
    """Verify expired state is ignored by cycle detection."""
    ancestor = TrackedValue()
    state = ancestor._state
    del ancestor
    gc.collect()
    assert state.obj() is None
    parent = CountingList()
    state.link(parent, None)
    parent.append(TrackedValue())

    assert len(parent) == 1
