"""Manage weak parent links, cycle checks, snapshots, and scoped captures."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TypeAlias, cast

from mutrack.internal.attributes import PARENTS_LOCK_STORE
from mutrack.internal.object_access import raw_getattr, raw_setattr
from mutrack.tracking.state.protocols import IState
from mutrack.tracking.trackable.protocols import ITrackable
from mutrack.tracking.types import Key

ParentKeys: TypeAlias = frozenset[Key]

ParentsSnapshot: TypeAlias = tuple[
    tuple[IState[ITrackable], ParentKeys],
    ...,
]

_LOCK_CREATION_LOCK = threading.Lock()


@dataclass(slots=True)
class _LinkCapture:
    """Capture touched child identities for one parent state.

    Attributes:
        state: Stable parent identity token observed by this capture.
        children: Touched children indexed by identity, or None after the
            capture closes.
    """

    state: IState[ITrackable]
    children: dict[int, ITrackable] | None


_LINK_CAPTURES: ContextVar[tuple[_LinkCapture, ...]] = ContextVar(
    "mutrack_link_captures", default=()
)


@contextmanager
def capture_parent_links(
    state: IState[ITrackable],
    /,
) -> Iterator[dict[int, ITrackable]]:
    """Capture child links touched during reentrant operations.

    Every matching active scope observes links and unlinks. Captures
    are context-local and do not retain children after the caller
    releases them.

    Args:
        state: Weak identity token of the parent whose links are accessed.

    Yields:
        A mutable identity mapping of children touched by matching link
        operations.
    """
    children: dict[int, ITrackable] = {}
    capture = _LinkCapture(state, children)
    token = _LINK_CAPTURES.set((*_LINK_CAPTURES.get(), capture))
    try:
        yield children
    finally:
        capture.children = None
        _LINK_CAPTURES.reset(token)


def _capture_child(
    child: ITrackable,
    state: IState[ITrackable],
    /,
) -> None:
    """Record a child in every active capture for its parent state.

    Args:
        child: Trackable child participating in the parent
            relationship.
        state: Weak identity token of the parent whose links are accessed.
    """
    for capture in _LINK_CAPTURES.get():
        if capture.state is state and capture.children is not None:
            capture.children[id(child)] = child


def _get_or_create_parents_lock(
    obj: ITrackable,
    /,
) -> threading.RLock:
    """Return the lazily initialized lock protecting a parent mapping.

    Args:
        obj: Trackable object whose bookkeeping is accessed.

    Returns:
        The unique reentrant lock protecting the object's parent
        mapping.
    """
    lock = raw_getattr(
        obj,
        PARENTS_LOCK_STORE,
        None,
    )

    if lock is not None:
        return cast(threading.RLock, lock)

    with _LOCK_CREATION_LOCK:
        lock = raw_getattr(
            obj,
            PARENTS_LOCK_STORE,
            None,
        )

        if lock is None:
            lock = threading.RLock()

            raw_setattr(
                obj,
                PARENTS_LOCK_STORE,
                lock,
            )

        return cast(threading.RLock, lock)


def link_parent(
    child: ITrackable,
    state: IState[ITrackable],
    key: Key,
    /,
) -> bool:
    """Add ``key`` to the child's link with ``state``.

    Returns ``True`` if the link did not exist before.

    Raises ``ValueError`` before changing links if the edge creates a
    cycle.

    Args:
        child: Trackable child participating in the parent
            relationship.
        state: Weak identity token of the parent whose links are accessed.
        key: Field name, container key, list index, or None for a set
            member.

    Returns:
        True if this key introduced a new parent-child reference.

    Raises:
        ValueError: The input would violate a cycle, depth, size, or
            state invariant.
    """
    parent = state.obj()

    if parent is not None:
        for ancestor in iter_ancestors(parent):
            if ancestor is child:
                raise ValueError("Cannot create cyclic tracking links.")

    lock = _get_or_create_parents_lock(child)

    with lock:
        _capture_child(child, state)
        parents = child._tracking_parents
        keys = parents.get(state)

        if keys is None:
            parents[state] = {key}
            return True

        if key in keys:
            return False

        keys.add(key)
        return True


def unlink_parent(
    child: ITrackable,
    state: IState[ITrackable],
    key: Key,
    /,
) -> bool:
    """Remove ``key`` from the child's link with ``state``.

    Returns ``True`` if the link existed.

    Args:
        child: Trackable child participating in the parent
            relationship.
        state: Weak identity token of the parent whose links are accessed.
        key: Field name, container key, list index, or None for a set
            member.

    Returns:
        True if the requested reference existed and was removed.
    """
    lock = _get_or_create_parents_lock(child)

    with lock:
        _capture_child(child, state)
        parents = child._tracking_parents
        keys = parents.get(state)

        if keys is None or key not in keys:
            return False

        keys.remove(key)

        if not keys:
            del parents[state]

        return True


def get_parents_snapshot(
    obj: ITrackable,
    /,
) -> ParentsSnapshot:
    """Snapshot parent states and keys under the object lock.

    The snapshot is taken under the per-object lock so propagation can
    iterate after releasing the lock.

    Args:
        obj: Trackable object whose bookkeeping is accessed.

    Returns:
        Parent state tokens paired with immutable referencing key sets.
    """
    lock = _get_or_create_parents_lock(obj)

    with lock:
        return tuple(
            (state, frozenset(keys))
            for state, keys in obj._tracking_parents.items()
        )


def iter_ancestors(obj: ITrackable, /) -> Iterator[ITrackable]:
    """Yield ``obj`` and its live ancestors once, using object identity.

    Snapshot one parent mapping at a time so traversal never holds
    several object locks. No strong references are retained after
    traversal.

    Args:
        obj: Object whose stored state or fields are accessed.

    Yields:
        The object followed by each live ancestor once, compared by
        identity.
    """
    pending = [obj]
    seen: set[int] = set()

    while pending:
        current = pending.pop()

        if id(current) in seen:
            continue

        seen.add(id(current))
        yield current

        for state, _ in get_parents_snapshot(current):
            parent = state.obj()

            if parent is not None:
                pending.append(parent)
