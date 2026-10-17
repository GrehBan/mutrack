from abc import ABC, abstractmethod
from typing_extensions import Self

from src.mutrack.tracking.state.protocols import IState
from src.mutrack.tracking.trackable.protocols import ITrackable, ParentsDictionary
from src.mutrack.tracking.factory import get_or_create_parents, get_or_create_state


class Trackable(ITrackable, ABC):
    @property
    def _parents(self) -> ParentsDictionary[ITrackable]:
        return get_or_create_parents(self)

    @property
    def _state(self) -> IState[Self]:
        return get_or_create_state(self)

    @abstractmethod
    def changed(self) -> None:
        raise NotImplementedError
