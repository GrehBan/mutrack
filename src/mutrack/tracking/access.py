from typing import TypeVar, cast, overload, Literal

from src.mutrack.internal.attributes import PARENTS_STORE, STATE_STORE, PENDING_CHANGE_STORE, CHANGE_SUPPRESS_LEVEL_STORE
from src.mutrack.internal.object_access import raw_getattr, raw_setattr
from src.mutrack.internal.sentinel import MISSING, _Missing
from src.mutrack.tracking.trackable.protocols import (
    ITrackable,
    ParentsDictionary,
    TrackableType
)
from src.mutrack.tracking.state.protocols import IState


T = TypeVar("T")


@overload
def get_parents(
    obj: ITrackable,
    /,
) -> ParentsDictionary[ITrackable]:
    ...


@overload
def get_parents(
    obj: ITrackable,
    default: Literal[None],
    /,
) -> ParentsDictionary[ITrackable] | None:
    ...


def get_parents(
    obj: ITrackable,
    default: _Missing | None = MISSING,
    /,
) -> ParentsDictionary[ITrackable] | None:
    if default is MISSING:
        return cast(
            ParentsDictionary[ITrackable],
            raw_getattr(obj, PARENTS_STORE),
        )

    return cast(
        ParentsDictionary[ITrackable] | None,
        raw_getattr(obj, PARENTS_STORE, None),
    )


@overload
def get_state(
    obj: TrackableType,
    /,
) -> IState[TrackableType]:
    ...


@overload
def get_state(
    obj: TrackableType,
    default: Literal[None],
    /,
) -> IState[TrackableType] | None:
    ...


def get_state(
    obj: TrackableType,
    default: _Missing | None = MISSING,
    /,
) -> IState[TrackableType] | None:
    if default is MISSING:
        return cast(
            IState[TrackableType],
            raw_getattr(obj, STATE_STORE),
        )

    return cast(
        IState[TrackableType] | None,
        raw_getattr(obj, STATE_STORE, None),
    )

def get_change_suppress_level(
    obj: ITrackable,
    /,
) -> int:
    return cast(
        int,
        raw_getattr(
            obj,
            CHANGE_SUPPRESS_LEVEL_STORE,
            0,
        ),
    )


def set_change_suppress_level(
    obj: ITrackable,
    value: int,
    /,
) -> None:
    if value < 0:
        raise ValueError(
            "Change suppression level cannot be negative."
        )

    raw_setattr(
        obj,
        CHANGE_SUPPRESS_LEVEL_STORE,
        value,
    )


def get_pending_change(
    obj: ITrackable,
    /,
) -> bool:
    return cast(
        bool,
        raw_getattr(
            obj,
            PENDING_CHANGE_STORE,
            False,
        ),
    )


def set_pending_change(
    obj: ITrackable,
    value: bool,
    /,
) -> None:
    raw_setattr(
        obj,
        PENDING_CHANGE_STORE,
        value,
    )