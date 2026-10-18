"""Provide a structural mixin for weak parent links and change propagation."""

from __future__ import annotations

from typing import ClassVar

from mutrack.tracking.constants import DEFAULT_MAX_DEPTH_LIMIT
from mutrack.tracking.events import propagate_change
from mutrack.tracking.factory import get_or_create_parents, get_or_create_state
from mutrack.tracking.state.protocols import IState
from mutrack.tracking.suppression import mark_change_or_defer
from mutrack.tracking.trackable.protocols import ITrackable, ParentsDictionary


class Trackable:
    """Structural ITrackable mixin, without a framework-specific metaclass.

    Attributes:
        _max_depth_limit: Default nesting limit used when callers omit
            max_depth.
    """

    _max_depth_limit: ClassVar[int] = DEFAULT_MAX_DEPTH_LIMIT

    @property
    def _tracking_parents(self) -> ParentsDictionary[ITrackable]:
        """Return the lazily initialized weak parent mapping.

        Returns:
            The weak mapping of parent states to referencing keys.
        """
        return get_or_create_parents(self)

    @property
    def _state(self) -> IState[ITrackable]:
        """Return the lazily initialized identity token for this object.

        Returns:
            The identity token used by children to reference this
            parent.
        """
        return get_or_create_state(self)

    def changed(self) -> None:
        """Emit a change notification or defer it to the active batch."""
        if not mark_change_or_defer(self):
            return
        self._emit_change()

    def _emit_change(self) -> None:
        """Propagate a change to live parents."""
        propagate_change(self)
