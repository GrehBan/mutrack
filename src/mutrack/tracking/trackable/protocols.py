from weakref import WeakKeyDictionary

from typing import Protocol, runtime_checkable, TypeVar, TypeAlias, TYPE_CHECKING, ClassVar
from src.mutrack.tracking.types import Key
from src.mutrack.tracking.constants import DEFAULT_MAX_DEPTH_LIMIT

if TYPE_CHECKING:
    from src.mutrack.tracking.state.protocols import IState

TrackableType = TypeVar("TrackableType", bound="ITrackable")
TrackableType_co = TypeVar("TrackableType_co", bound="ITrackable", covariant=True)
ParentsDictionary: TypeAlias = WeakKeyDictionary[
    "IState[TrackableType]",
    Key,
]


@runtime_checkable
class ITrackable(Protocol):
    _max_depth_limit: ClassVar[int] = DEFAULT_MAX_DEPTH_LIMIT

    """Interface for trackable objects."""

    @property
    def _parents(self) -> ParentsDictionary:
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
