"""Access object storage without framework or property hooks."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from types import GetSetDescriptorType, MemberDescriptorType
from typing import Any, TypeVar, overload

from mutrack.internal.sentinel import MISSING

T = TypeVar("T")


@overload
def raw_getattr(
    obj: object,
    name: str,
    /,
) -> object: ...


@overload
def raw_getattr(
    obj: object,
    name: str,
    default: T,
    /,
) -> object | T: ...


def raw_getattr(
    obj: object,
    name: str,
    default: object = MISSING,
    /,
) -> object:
    """Read an attribute without custom lookup hooks.

    Object access still honors descriptors; use stored-field helpers
    when properties must not run.

    Args:
        obj: Object whose stored state or fields are accessed.
        name: Stored attribute or declared field name.
        default: Fallback used when the requested value is absent.

    Returns:
        The stored attribute value or the supplied fallback.
    """
    try:
        return object.__getattribute__(obj, name)
    except AttributeError:
        if default is MISSING:
            raise

        return default


def raw_setattr(obj: object, name: str, value: Any) -> None:
    """Write an attribute without custom assignment hooks.

    Object assignment still honors data descriptors. Stored-field
    replacement must use set_stored_field to bypass property setters
    too.

    Args:
        obj: Object whose stored state or fields are accessed.
        name: Stored attribute or declared field name.
        value: Replacement value written to storage.
    """
    return object.__setattr__(obj, name, value)


def get_instance_dict(obj: object, /) -> dict[str, object] | None:
    """Read dictionary storage through its genuine declaring descriptor.

    Args:
        obj: Object whose stored state or fields are accessed.

    Returns:
        The real instance dictionary, or None when no dictionary
        exists.
    """
    for cls in type(obj).__mro__:
        descriptor = cls.__dict__.get("__dict__")
        if isinstance(
            descriptor, (GetSetDescriptorType, MemberDescriptorType)
        ):
            namespace: object = descriptor.__get__(obj, type(obj))
            if isinstance(namespace, dict):
                return namespace
    return None


def iter_slot_descriptors(
    obj: object, /
) -> Iterator[tuple[str, MemberDescriptorType]]:
    """Yield declared slot storage without resolving instance attributes.

    Args:
        obj: Object whose stored state or fields are accessed.

    Yields:
        Normalized slot names paired with their genuine declaring
        descriptors.
    """
    for cls in type(obj).__mro__:
        for name, descriptor in cls.__dict__.items():
            if (
                name not in {"__dict__", "__weakref__"}
                and isinstance(descriptor, MemberDescriptorType)
                and descriptor.__objclass__ is cls
            ):
                yield name, descriptor


def iter_stored_fields(obj: object, /) -> Iterator[tuple[str, object]]:
    """Yield physical dictionary and slot values, never user descriptors.

    Args:
        obj: Object whose stored state or fields are accessed.

    Yields:
        Stored attribute names and values, with dictionary entries
        taking precedence.
    """
    namespace = get_instance_dict(obj)
    seen: set[str] = set()
    if namespace is not None:
        for name, value in tuple(namespace.items()):
            seen.add(name)
            yield name, value
    for name, descriptor in iter_slot_descriptors(obj):
        if name in seen:
            continue
        try:
            value = descriptor.__get__(obj, type(obj))
        except AttributeError:
            continue
        seen.add(name)
        yield name, value


def iter_declared_fields(
    obj: object, names: Iterable[str], /
) -> Iterator[tuple[str, object]]:
    """Read available declared fields in order, including stored defaults.

    Args:
        obj: Object whose stored state or fields are accessed.
        names: Declared field names in their required iteration order.

    Yields:
        Available declared field names and their stored values.
    """
    stored = dict(iter_stored_fields(obj))
    for name in names:
        if name in stored:
            yield name, stored[name]


def set_stored_field(
    obj: object, name: str, value: object, /, *, create: bool = False
) -> None:
    """Replace existing storage without assignment or property hooks.

    Follow iter_stored_fields' dictionary-first precedence, including
    inherited slots shadowed by subclass properties. Do not create
    fields.

    Args:
        obj: Object receiving the raw stored field replacement.
        name: Stored attribute or declared field name.
        value: Replacement value written to storage.
        create: Whether restoration may recreate an unavailable field.

    Raises:
        AttributeError: The requested attribute has no available stored
            value.
    """
    namespace = get_instance_dict(obj)
    if namespace is not None and name in namespace:
        namespace[name] = value
        return
    for slot_name, descriptor in iter_slot_descriptors(obj):
        if slot_name != name:
            continue
        if not create:
            try:
                descriptor.__get__(obj, type(obj))
            except AttributeError:
                continue
        descriptor.__set__(obj, value)
        return
    if create and namespace is not None:
        namespace[name] = value
        return
    raise AttributeError(f"No stored field {name!r} on {type(obj).__name__}.")


def delete_stored_field(obj: object, name: str, /) -> None:
    """Delete stored field data without invoking assignment hooks.

    Args:
        obj: Object whose dictionary or slot storage is changed.
        name: Stored field name to remove.

    Raises:
        AttributeError: No available storage has the requested name.
    """
    namespace = get_instance_dict(obj)
    if namespace is not None and name in namespace:
        del namespace[name]
        return
    for slot_name, descriptor in iter_slot_descriptors(obj):
        if slot_name == name:
            descriptor.__delete__(obj)
            return
    raise AttributeError(name)
