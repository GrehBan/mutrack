"""Regression tests for wrapping."""

from __future__ import annotations

from typing import Any

import pytest

from mutrack.adapters.sqlalchemy.collections.registry import (
    get_sqlalchemy_containers,
)
from mutrack.tracking.wrapping import (
    ContainerTypes,
    prepare_value,
    prepare_values,
    wrap_value,
)
from tests.helpers import CountingList, TrackedValue


def prepare(value: object, depth: int, operation: str) -> Any:
    """Prepare a value using the selected wrapping entry point.

    Args:
        value: Value to read, prepare, store, or compare.
        depth: Current one-based depth within the graph or preparation
            operation.
        operation: Mutation callback or wrapping entry point exercised
            by the call.

    Returns:
        The value prepared through the requested public API.
    """
    containers = get_sqlalchemy_containers()
    if operation == "prepare_value":
        return prepare_value(value, containers=containers, max_depth=depth)
    if operation == "prepare_values":
        return prepare_values([value], containers=containers, max_depth=depth)[
            0
        ]
    return wrap_value(
        CountingList(), value, 0, containers=containers, max_depth=depth
    )


@pytest.mark.parametrize(
    "operation", ["prepare_value", "prepare_values", "wrap_value"]
)
@pytest.mark.parametrize("deep_first", [False, True])
@pytest.mark.parametrize("depth", [4, 5])
def test_shared_subtree_depth_is_independent_of_visit_order(
    operation: str, deep_first: bool, depth: int
) -> None:
    """Verify shared subtree depth is independent of visit order.

    Args:
        operation: Mutation callback or wrapping entry point exercised
            by the call.
        deep_first: Whether the deeper shared-reference path is visited
            first.
        depth: Current one-based depth within the graph or preparation
            operation.
    """
    child = TrackedValue()
    shared = [child, []]
    incoming = [[[shared]], shared] if deep_first else [shared, [[shared]]]

    if depth == 4:
        with pytest.raises(ValueError, match="max depth"):
            prepare(incoming, depth, operation)
        assert not child._tracking_parents
    else:
        result = prepare(incoming, depth, operation)
        shallow = result[1 if deep_first else 0]
        deep = result[0 if deep_first else 1][0][0]
        assert shallow is deep
        assert shallow[0] is child


@pytest.mark.parametrize("deep_first", [False, True])
def test_batch_roots_share_height_validation(deep_first: bool) -> None:
    """Verify batch roots share height validation.

    Args:
        deep_first: Whether the deeper shared-reference path is visited
            first.
    """
    shared = [[]]
    roots = [[[shared]], shared] if deep_first else [shared, [[shared]]]
    containers = get_sqlalchemy_containers()

    with pytest.raises(ValueError, match="max depth"):
        prepare_values(roots, containers=containers, max_depth=3)

    result: Any = prepare_values(roots, containers=containers, max_depth=4)
    assert (
        result[1 if deep_first else 0] is result[0 if deep_first else 1][0][0]
    )


def test_dictionary_and_set_subtrees_count_toward_height() -> None:
    """Verify dictionary and set subtrees count toward height."""
    shared = {"leaf": set()}
    incoming = {"shallow": shared, "deep": {"one": {"two": shared}}}

    with pytest.raises(ValueError, match="max depth"):
        prepare(incoming, 4, "prepare_value")

    result = prepare(incoming, 5, "prepare_value")
    assert result["shallow"] is result["deep"]["one"]["two"]


def test_existing_trackables_remain_depth_terminals() -> None:
    """Verify existing trackables remain depth terminals."""
    child = CountingList([[[1]]])
    result = prepare({"child": child}, 1, "prepare_value")

    assert result["child"] is child


def test_shared_dag_wraps_each_container_once() -> None:
    """Verify shared dag wraps each container once."""

    class CountedList(CountingList):
        """Count wrapper construction to verify memoized DAG preparation."""

        created = 0

        def __init__(self) -> None:
            """Initialize the stored values used by this object."""
            type(self).created += 1
            super().__init__()

    containers = get_sqlalchemy_containers()
    registry = ContainerTypes(
        list_type=CountedList,
        dict_type=containers.dict_type,
        set_type=containers.set_type,
    )
    incoming: list[Any] = []
    for _ in range(20):
        incoming = [incoming, incoming]

    result: Any = prepare_value(incoming, containers=registry, max_depth=21)

    assert CountedList.created == 21
    for _ in range(20):
        assert result[0] is result[1]
        result = result[0]
    assert result == []


def test_depth_failure_does_not_mutate_destination_or_commit_links() -> None:
    """Verify depth failure does not mutate destination or commit links."""

    class LimitedList(CountingList):
        """Apply a small wrapping-depth limit for boundary validation."""

        _max_depth_limit = 4

    child = TrackedValue()
    shared = [child, []]
    destination = LimitedList([1])

    with pytest.raises(ValueError, match="max depth"):
        destination.append([shared, [[shared]]])

    assert destination == [1]
    assert not child._tracking_parents
    assert destination.notifications == 0
