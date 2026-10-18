"""Snapshot collection children and update graph edges."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import TypeAlias, cast

from mutrack.tracking.graph.linking.base import unlink_child
from mutrack.tracking.graph.traversal import iter_children
from mutrack.tracking.state.protocols import IState
from mutrack.tracking.trackable.protocols import ITrackable, is_trackable
from mutrack.tracking.types import Key


@dataclass(slots=True)
class _ChildLinks:
    """Associate a retained child identity with its parent keys.

    Attributes:
        child: Child retained by identity for graph bookkeeping.
        keys: All locations referencing this child from one parent.
    """

    child: ITrackable
    keys: set[Key] = field(default_factory=set)


ChildLinksSnapshot: TypeAlias = dict[int, _ChildLinks]

LinkEntry: TypeAlias = tuple[Key, ITrackable]


def unlink_childrens(
    parent: ITrackable,
    /,
) -> None:
    """Unlink all direct trackable children from parent.

    Args:
        parent: Trackable owner of the child reference.
    """
    for key, child in tuple(iter_children(parent)):
        if not is_trackable(child):
            continue

        unlink_child(
            parent,
            child,
            key,
        )


def link_childrens(
    parent: ITrackable,
    /,
) -> None:
    """Link all direct trackable children to parent transactionally.

    Args:
        parent: Trackable owner of the child reference.
    """
    link_entries(
        parent,
        (
            (key, child)
            for key, child in tuple(iter_children(parent))
            if is_trackable(child)
        ),
    )


def iter_trackable_items(
    values: Sequence[object],
    start: int = 0,
    /,
) -> Iterator[tuple[int, ITrackable]]:
    """Yield ``(start + offset, value)`` for every trackable value.

    Distinct value types are collected at C speed first, so sequences
    that hold no trackable values (e.g. lists of scalars) are rejected
    without a Python-level loop over their items.

    Args:
        values: Incoming values processed by the operation.
        start: Inclusive starting position or index offset.

    Yields:
        The original sequence index and its Trackable value.
    """
    if not values:
        return

    representatives = dict(
        zip(
            map(type, values),
            values,
        )
    )

    trackable_types = {
        value_type
        for value_type, value in representatives.items()
        if is_trackable(value)
    }

    if not trackable_types:
        return

    if len(trackable_types) == len(representatives):
        yield from cast(
            Iterator[tuple[int, ITrackable]],
            enumerate(values, start),
        )
        return

    for index, value in enumerate(values, start):
        if type(value) in trackable_types:
            yield index, cast(ITrackable, value)


def add_child_links(
    snapshot: ChildLinksSnapshot,
    entries: Iterable[LinkEntry],
    /,
) -> ChildLinksSnapshot:
    """Add trackable ``(key, child)`` entries to ``snapshot`` in place.

    Args:
        snapshot: Mutable identity-keyed child-link snapshot to extend.
        entries: Parent-key and child pairs to snapshot, link, or
            unlink.

    Returns:
        The supplied snapshot after adding the requested references.
    """
    for key, child in entries:
        identity = id(child)

        entry = snapshot.get(identity)

        if entry is None:
            entry = _ChildLinks(
                child=child,
            )
            snapshot[identity] = entry

        entry.keys.add(key)

    return snapshot


def snapshot_child_links(
    entries: Iterable[tuple[Key, object]],
    /,
) -> ChildLinksSnapshot:
    """Snapshot the trackable values among arbitrary ``(key, value)`` pairs.

    Args:
        entries: Parent-key and child pairs to snapshot, link, or
            unlink.

    Returns:
        A snapshot keyed by child identity with referencing keys
        grouped.
    """
    return add_child_links(
        {},
        ((key, value) for key, value in entries if is_trackable(value)),
    )


def snapshot_sequence_links(
    values: Sequence[object],
    start: int = 0,
    /,
) -> ChildLinksSnapshot:
    """Snapshot trackable values of a sequence slice beginning at ``start``.

    Args:
        values: Incoming values processed by the operation.
        start: Inclusive starting position or index offset.

    Returns:
        A child snapshot retaining the original sequence indices.
    """
    return add_child_links(
        {},
        iter_trackable_items(
            values,
            start,
        ),
    )


def link_entries(
    parent: ITrackable,
    entries: Iterable[LinkEntry],
    /,
) -> list[LinkEntry]:
    """Link trackable children to ``parent`` transactionally.

    Returns the links that did not exist before. If linking fails,
    exactly those links are removed again and the original exception is
    re-raised; pre-existing links are never touched.

    The parent's state is only materialized if there is something to
    link.

    Args:
        parent: Trackable owner of the child reference.
        entries: Parent-key and child pairs to snapshot, link, or
            unlink.

    Returns:
        Only the edges newly created by this call.
    """
    state: IState[ITrackable] | None = None

    created: list[LinkEntry] = []

    try:
        for key, child in entries:
            if state is None:
                state = parent._state

            if state.link(child, key):
                created.append((key, child))

    except Exception:
        if state is not None:
            _rollback_links(
                state,
                created,
            )
        raise

    return created


def unlink_entries(
    parent: ITrackable,
    entries: Iterable[LinkEntry],
    /,
) -> None:
    """Remove the given ``(key, child)`` links from ``parent``.

    Args:
        parent: Trackable owner of the child reference.
        entries: Parent-key and child pairs to snapshot, link, or
            unlink.
    """
    state: IState[ITrackable] | None = None

    for key, child in entries:
        if state is None:
            state = parent._state

        state.unlink(child, key)


def _rollback_links(
    state: IState[ITrackable],
    created: list[LinkEntry],
    /,
) -> None:
    """Remove newly created links in reverse order after a failure.

    Args:
        state: Weak identity token of the parent whose links are accessed.
        created: Newly created edges eligible for rollback.
    """
    for key, child in reversed(created):
        try:
            state.unlink(child, key)
        except Exception:
            pass


def reconcile_child_links(
    parent: ITrackable,
    before: ChildLinksSnapshot,
    after: ChildLinksSnapshot,
    /,
) -> None:
    """Reconcile child keys transactionally against the desired snapshot.

    Args:
        parent: Trackable owner of the child reference.
        before: Child references and keys before the operation.
        after: Desired child references and keys after the operation.
    """
    if not before and not after:
        return

    additions: list[LinkEntry] = []
    removals: list[LinkEntry] = []

    for identity, new in after.items():
        previous = before.get(identity)
        additions.extend(
            (key, new.child)
            for key in new.keys
            if previous is None or key not in previous.keys
        )

    for identity, old in before.items():
        following = after.get(identity)
        removals.extend(
            (key, old.child)
            for key in old.keys
            if following is None or key not in following.keys
        )

    link_entries(parent, additions)
    unlink_entries(parent, removals)
