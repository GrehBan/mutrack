"""Define the weak state-token interface used to identify parent objects."""

from typing import Protocol, runtime_checkable

from mutrack.tracking.trackable.protocols import ITrackable, TrackableType_co
from mutrack.tracking.types import Key


@runtime_checkable
class IState(Protocol[TrackableType_co]):
    """Interface for state objects that can be tracked."""

    def obj(self) -> TrackableType_co | None:
        """Return the parent object from the weak reference.

        This method fulfills the SQLAlchemy Mutable parent protocol,
        allowing this state token to be used directly in SQLAlchemy's
        `_parents` dictionary.

        Returns:
            The dereferenced parent object, or None if it has been
            collected.
        """
        ...

    def link(self, child: ITrackable, key: Key) -> bool:
        """Establish a tracking connection between this state and a child.

        Registers this `MutableState` instance in the child's
        `_parents` dictionary. This enables the child to bubble up
        mutation events to the parent.

        The operation is thread-safe using a recursive lock.

        Args:
            child: The child object that should track this parent
                state.
            key: The attribute name or collection index where the child
                is stored within the parent.

        Returns:
            True if the link did not exist before.
        """
        ...

    def unlink(self, child: ITrackable, key: Key) -> bool:
        """Break the tracking connection between this state and a child.

        Removes this `MutableState` instance from the child's
        `_parents` dictionary.

        The operation is thread-safe using a recursive lock.

        Args:
            child: The child object to disconnect from this parent
                state.
            key: The attribute name or collection index where the child
                is stored within the parent.

        Returns:
            True if the link existed.
        """
        ...
