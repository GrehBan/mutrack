"""Represent parent identity using a weak reference to the owning object."""

import weakref

from mutrack.tracking.parents import link_parent, unlink_parent
from mutrack.tracking.state.protocols import IState
from mutrack.tracking.trackable.protocols import ITrackable, TrackableType_co
from mutrack.tracking.types import Key


class MutableState(IState[TrackableType_co]):
    """A mutable state object that can be tracked by child objects.

    Weak-referenceability is inherited from IState. The token stores a
    weak reference and never keeps the parent alive.
    """

    __slots__ = ("_ref",)

    def __init__(self, obj: TrackableType_co):
        """Create a state token holding only a weak reference to its owner.

        Args:
            obj: Object whose stored state or fields are accessed.
        """
        self._ref = weakref.ref(obj)

    def obj(self) -> TrackableType_co | None:
        """Return the live object referenced by this state token.

        Returns:
            The live owner, or None after its weak reference expires.
        """
        return self._ref()

    def link(
        self,
        child: ITrackable,
        key: Key,
    ) -> bool:
        """Register a child key under this weak parent identity token.

        Args:
            child: Trackable child participating in the parent
                relationship.
            key: Field name, container key, list index, or None for a
                set member.

        Returns:
            True if the parent-child key was newly registered.
        """
        return link_parent(child, self, key)

    def unlink(self, child: ITrackable, key: Key) -> bool:
        """Remove a child key registered under this parent identity token.

        Args:
            child: Trackable child participating in the parent
                relationship.
            key: Field name, container key, list index, or None for a
                set member.

        Returns:
            True if the requested parent-child key was removed.
        """
        return unlink_parent(child, self, key)
