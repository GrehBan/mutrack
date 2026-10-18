"""Access tracking state without creating graph edges."""

from typing import Literal, TypeVar, cast, overload

from mutrack.internal.attributes import (
    CHANGE_SUPPRESS_LEVEL_STORE,
    PARENTS_STORE,
    PENDING_CHANGE_STORE,
    STATE_STORE,
)
from mutrack.internal.object_access import raw_getattr, raw_setattr
from mutrack.internal.sentinel import MISSING, _Missing
from mutrack.tracking.state.protocols import IState
from mutrack.tracking.trackable.protocols import (
    ITrackable,
    ParentsDictionary,
    TrackableType,
)

T = TypeVar("T")


@overload
def get_parents(
    obj: ITrackable,
    /,
) -> ParentsDictionary[ITrackable]: ...


@overload
def get_parents(
    obj: ITrackable,
    default: Literal[None],
    /,
) -> ParentsDictionary[ITrackable] | None: ...


def get_parents(
    obj: ITrackable,
    default: _Missing | None = MISSING,
    /,
) -> ParentsDictionary[ITrackable] | None:
    """Read an existing parent mapping without initializing it.

    ParentsDictionary is subscripted only in annotations and quoted
    casts because its runtime class is not a generic alias.

    Args:
        obj: Trackable object whose bookkeeping is accessed.
        default: Fallback used when the requested value is absent.

    Returns:
        The existing weak parent mapping, or the requested None
        fallback.
    """
    if default is MISSING:
        return cast(
            "ParentsDictionary[ITrackable]",
            raw_getattr(obj, PARENTS_STORE),
        )

    return cast(
        "ParentsDictionary[ITrackable] | None",
        raw_getattr(obj, PARENTS_STORE, None),
    )


@overload
def get_state(
    obj: TrackableType,
    /,
) -> IState[TrackableType]: ...


@overload
def get_state(
    obj: TrackableType,
    default: Literal[None],
    /,
) -> IState[TrackableType] | None: ...


def get_state(
    obj: TrackableType,
    default: _Missing | None = MISSING,
    /,
) -> IState[TrackableType] | None:
    """Read an existing state token without initializing it.

    Args:
        obj: Trackable object whose bookkeeping is accessed.
        default: Fallback used when the requested value is absent.

    Returns:
        The existing state token, or the requested None fallback.
    """
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
    """Read the current nesting level of change suppression.

    Args:
        obj: Object whose stored state or fields are accessed.

    Returns:
        The current nonnegative suppression nesting level.
    """
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
    """Set the nesting level of change suppression.

    Args:
        obj: Object whose stored state or fields are accessed.
        value: New nesting level for change suppression.

    Raises:
        ValueError: The input would violate a cycle, depth, size, or
            state invariant.
    """
    if value < 0:
        raise ValueError("Change suppression level cannot be negative.")

    raw_setattr(
        obj,
        CHANGE_SUPPRESS_LEVEL_STORE,
        value,
    )


def get_pending_change(
    obj: ITrackable,
    /,
) -> bool:
    """Check whether a suppressed change is waiting to be emitted.

    Args:
        obj: Object whose stored state or fields are accessed.

    Returns:
        True when a deferred notification is pending.
    """
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
    """Record whether a suppressed change is pending.

    Args:
        obj: Object whose stored state or fields are accessed.
        value: Whether a deferred change notification is pending.
    """
    raw_setattr(
        obj,
        PENDING_CHANGE_STORE,
        value,
    )
