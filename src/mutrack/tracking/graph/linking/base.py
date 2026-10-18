"""Link and unlink individual framework-neutral parent-child graph edges."""

from __future__ import annotations

from mutrack.tracking.trackable.protocols import ITrackable
from mutrack.tracking.types import Key


def link_child(
    parent: ITrackable,
    child: ITrackable,
    key: Key,
    /,
) -> bool:
    """Link a trackable child to its parent.

    The parent's state is used as the stable identity token stored in
    the child's parent mapping.

    Multiple keys may point from the same parent to the same child.

    Returns ``True`` if the link did not exist before.

    Args:
        parent: Trackable owner of the child reference.
        child: Trackable child participating in the parent
            relationship.
        key: Field name, container key, list index, or None for a set
            member.

    Returns:
        True if the edge did not already exist.
    """
    return parent._state.link(
        child,
        key,
    )


def unlink_child(
    parent: ITrackable,
    child: ITrackable,
    key: Key,
    /,
) -> bool:
    """Remove one parent-child relation.

    Only the specified key is removed. The parent state remains linked
    while at least one other key still references the child.

    Returns ``True`` if the link existed.

    Args:
        parent: Trackable owner of the child reference.
        child: Trackable child participating in the parent
            relationship.
        key: Field name, container key, list index, or None for a set
            member.

    Returns:
        True if the edge existed and was removed.
    """
    return parent._state.unlink(
        child,
        key,
    )
