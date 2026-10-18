"""Define Trackable contracts and check structural support per instance."""

from typing import (
    TYPE_CHECKING,
    ClassVar,
    Protocol,
    TypeAlias,
    TypeGuard,
    TypeVar,
    runtime_checkable,
)
from weakref import WeakKeyDictionary

from mutrack.tracking.types import Key

if TYPE_CHECKING:
    from mutrack.tracking.state.protocols import IState

TrackableType = TypeVar("TrackableType", bound="ITrackable")
TrackableType_co = TypeVar(
    "TrackableType_co",
    bound="ITrackable",
    covariant=True,
)
ParentsDictionary: TypeAlias = WeakKeyDictionary[
    "IState[TrackableType]",
    set[Key],
]


@runtime_checkable
class ITrackable(Protocol):
    """Define tracked objects and their parent notifications.

    Attributes:
        _max_depth_limit: Default nesting limit used when callers omit
            max_depth.
    """

    _max_depth_limit: ClassVar[int]

    @property
    def _tracking_parents(self) -> "ParentsDictionary[ITrackable]":
        """Retrieve or initialize the parents WeakKeyDictionary.

        Returns:
            A WeakKeyDictionary mapping parent states to keys.
        """
        ...

    @property
    def _state(self) -> "IState[ITrackable]":
        """Retrieve or initialize the unique identity token.

        Created lazily and stored strongly on the object.

        Returns:
            The MutableState token for this object.
        """
        ...

    def changed(self) -> None:
        """Notify parents using the library's safe propagation logic."""
        ...


def is_trackable(value: object, /) -> TypeGuard[ITrackable]:
    """Check Trackable support without caching instance-specific members.

    Structural implementations may install protocol members on individual
    instances, so objects of the same type can have different support.

    Args:
        value: Object checked for the Trackable protocol.

    Returns:
        True when the value implements the Trackable protocol.
    """
    return isinstance(value, ITrackable)
