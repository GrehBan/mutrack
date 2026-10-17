from typing import TypeVar, overload, Any

from src.mutrack.internal.sentinel import MISSING

T = TypeVar("T")


@overload
def raw_getattr(
    obj: object,
    name: str,
    /,
) -> object:
    ...


@overload
def raw_getattr(
    obj: object,
    name: str,
    default: T,
    /,
) -> object | T:
    ...


def raw_getattr(
    obj: object,
    name: str,
    default: object = MISSING,
    /,
) -> object:
    try:
        return object.__getattribute__(obj, name)
    except AttributeError:
        if default is MISSING:
            raise

        return default


def raw_setattr(
    obj: object,
    name: str,
    value: Any
) -> None:
    return object.__setattr__(obj, name, value)