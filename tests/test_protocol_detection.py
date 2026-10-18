"""Check Trackable support for instance-defined structural members."""

from __future__ import annotations

from typing import ClassVar
from weakref import WeakKeyDictionary

import pytest

from mutrack.adapters.plain.fields import PLAIN_FIELDS
from mutrack.tracking.build import build_graph
from mutrack.tracking.events import propagate_change
from mutrack.tracking.state.protocols import IState
from mutrack.tracking.state.state import MutableState
from mutrack.tracking.trackable.protocols import (
    ITrackable,
    ParentsDictionary,
    is_trackable,
)
from tests.graph_support import CONTAINERS, NeutralList


class InstanceTracked:
    """Install tracking storage on initialized instances without a mixin."""

    _max_depth_limit: ClassVar[int] = 20
    _state: IState[ITrackable]
    _tracking_parents: ParentsDictionary[ITrackable]

    def __init__(self, initialized: bool) -> None:
        """Create model fields and optionally initialize structural tracking.

        Args:
            initialized: Whether this instance implements the full protocol.
        """
        self.tags: list[str] = []
        self.notifications = 0
        if initialized:
            self.initialize_tracking()

    def initialize_tracking(self) -> None:
        """Install the instance-only members required by ITrackable."""
        self._state = MutableState(self)
        self._tracking_parents = WeakKeyDictionary()

    def changed(self) -> None:
        """Count changes and propagate them through the instance's parents."""
        self.notifications += 1
        propagate_change(self)


@pytest.mark.parametrize("initialized_first", [False, True])
def test_protocol_support_is_checked_per_instance(
    initialized_first: bool,
) -> None:
    """Keep support results independent of other instances of the same type.

    Args:
        initialized_first: Whether to check the fully initialized model first.
    """
    ready, incomplete = InstanceTracked(True), InstanceTracked(False)
    ordered = (ready, incomplete) if initialized_first else (incomplete, ready)
    for value in (*ordered, *reversed(ordered)):
        assert is_trackable(value) is isinstance(value, ITrackable)
        assert is_trackable(value) is (value is ready)

    build_graph(ready, containers=CONTAINERS, fields=PLAIN_FIELDS)
    assert isinstance(ready.tags, NeutralList)
    assert ready.tags._tracking_parents[ready._state] == {"tags"}
    assert ready.notifications == 0
    ready.tags.append("new")
    assert ready.notifications == 1

    original = incomplete.tags
    with pytest.raises(TypeError, match="ITrackable"):
        build_graph(incomplete, containers=CONTAINERS, fields=PLAIN_FIELDS)
    assert incomplete.tags is original
    assert type(incomplete.tags) is list


def test_protocol_support_can_change_on_the_same_instance() -> None:
    """Observe installation and removal of instance-defined protocol members."""
    value = InstanceTracked(False)
    assert not is_trackable(value)
    value.initialize_tracking()
    assert is_trackable(value)
    object.__delattr__(value, "_state")
    assert not is_trackable(value)
