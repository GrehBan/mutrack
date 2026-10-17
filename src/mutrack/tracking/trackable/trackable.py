from typing_extensions import Self

from mutrack.tracking.state.protocols import IState
from mutrack.tracking.trackable.protocols import ITrackable, ParentsDictionary
from mutrack.tracking.factory import get_or_create_parents, get_or_create_state
from mutrack.tracking.suppression import mark_change_or_defer
from mutrack.tracking.events import propagate_change


class Trackable(ITrackable):
    @property
    def _tracking_parents(self) -> ParentsDictionary[ITrackable]:
        return get_or_create_parents(self)

    @property
    def _state(self) -> IState[Self]:
        return get_or_create_state(self)

    def changed(self) -> None:
        if not mark_change_or_defer(self):
            return
        self._emit_change()

    def _emit_change(self) -> None:
        propagate_change(self)
