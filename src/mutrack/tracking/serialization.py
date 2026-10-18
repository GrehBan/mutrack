"""Encode stored model fields and decode annotated JSON document values."""

from __future__ import annotations

import types
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import (
    Annotated,
    Any,
    Literal,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)
from uuid import UUID

from mutrack.introspection.inspection import is_internal_attribute
from mutrack.tracking.field_access import FieldAccess
from mutrack.tracking.trackable.protocols import is_trackable


def validate_json_input(value: object, max_depth: int) -> None:
    """Reject cyclic or excessively deep input before recursive typed decoding.

    Args:
        value: Incoming document tree, possibly containing shared containers.
        max_depth: Maximum permitted document container depth.

    Raises:
        ValueError: A cycle or depth-limit violation is encountered.
    """
    active: set[int] = set()
    heights: dict[int, int] = {}
    pending = [(value, 1, False)]
    while pending:
        node, depth, leaving = pending.pop()
        if not isinstance(node, (dict, list, tuple, set, frozenset)):
            continue
        children = (
            list(node.values()) if isinstance(node, dict) else list(node)
        )
        identity = id(node)
        if leaving:
            active.remove(identity)
            heights[identity] = 1 + max(
                (heights.get(id(child), 0) for child in children), default=0
            )
            continue
        if identity in active:
            raise ValueError("Cannot decode cyclic documents.")
        if depth + heights.get(identity, 1) - 1 > max_depth:
            raise ValueError("Document nesting exceeds max depth.")
        if identity in heights:
            continue
        active.add(identity)
        pending.append((node, depth, True))
        pending.extend(
            (child, depth + 1, False) for child in reversed(children)
        )


def encode_json(value: object, fields: FieldAccess, /) -> object:
    """Encode declared fields without serializing tracking bookkeeping.

    Args:
        value: Model or JSON-compatible value to encode.
        fields: Adapter selecting available stored model fields.

    Returns:
        A JSON-compatible tree containing only application values.
    """
    return _encode(value, fields, set())


def _encode(value: object, fields: FieldAccess, active: set[int]) -> object:
    """Encode a tree while detecting cycles along the active path.

    Args:
        value: Current document value.
        fields: Adapter discovering model fields.
        active: Object identities on the current encoding path.

    Returns:
        A JSON-compatible value with shared objects duplicated as JSON data.

    Raises:
        TypeError: The value or dictionary key has no default JSON encoding.
        ValueError: A cycle is encountered during encoding.
    """
    if isinstance(value, Enum):
        return _encode(value.value, fields, active)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if id(value) in active:
        raise ValueError("Cannot serialize cyclic documents.")
    active.add(id(value))
    try:
        if is_trackable(value) and fields.supports(value):
            return {
                key: _encode(child, fields, active)
                for key, child in fields.iter_fields(value)
            }
        if isinstance(value, dict):
            if not all(isinstance(key, str) for key in value):
                raise TypeError(
                    "JSON document dictionary keys must be strings."
                )
            return {
                key: _encode(child, fields, active)
                for key, child in value.items()
            }
        if isinstance(value, (list, tuple, set, frozenset)):
            return [_encode(child, fields, active) for child in value]
        raise TypeError(f"No JSON encoding for {type(value).__name__}.")
    finally:
        active.remove(id(value))


def decode_json(value: object, annotation: Any, fields: FieldAccess) -> Any:
    """Reconstruct annotated containers and models through native constructors.

    Args:
        value: JSON-compatible database or assignment input.
        annotation: Expected Python type, including nested container types.
        fields: Adapter supplying optional framework construction semantics.

    Returns:
        A typed value, with framework constructors performing validation.

    Raises:
        TypeError: A model requires object data or a typed shape is invalid.
        ValueError: No union alternative or literal matches the input.
    """
    if annotation in (Any, object) or isinstance(annotation, str):
        return value
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Annotated:
        return decode_json(value, args[0], fields)
    if origin in (Union, types.UnionType):
        for candidate in args:
            try:
                return decode_json(value, candidate, fields)
            except (TypeError, ValueError):
                continue
        raise ValueError("Document does not match its union annotation.")
    if annotation is type(None):
        if value is not None:
            raise TypeError("Expected null.")
        return None
    if origin is Literal:
        if value not in args:
            raise ValueError("Document does not match its literal annotation.")
        return value
    if origin in (list, set, frozenset, tuple):
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise TypeError("Expected array data.")
        if origin is tuple and args and args[-1] is not Ellipsis:
            if len(args) != len(value):
                raise TypeError("Tuple length does not match its annotation.")
            return tuple(
                decode_json(item, item_type, fields)
                for item, item_type in zip(value, args)
            )
        item_type = args[0] if args else Any
        return origin(decode_json(item, item_type, fields) for item in value)
    if origin is dict:
        if not isinstance(value, dict):
            raise TypeError("Expected object data.")
        key_type, item_type = args if args else (Any, Any)
        return {
            decode_json(key, key_type, fields): decode_json(
                item, item_type, fields
            )
            for key, item in value.items()
        }
    if isinstance(annotation, type):
        if isinstance(value, annotation):
            return value
        if issubclass(annotation, Enum):
            return annotation(value)
        if annotation in (datetime, date, time):
            if not isinstance(value, str):
                raise TypeError("Expected an ISO date or time string.")
            return annotation.fromisoformat(value)
        if annotation in (UUID, Decimal):
            if not isinstance(value, str):
                raise TypeError("Expected a serialized string.")
            return annotation(value)
        if annotation in (str, int, float, bool):
            raise TypeError(f"Expected {annotation.__name__}.")
        if not isinstance(value, dict):
            raise TypeError("Model documents require object data.")
        if any(
            not isinstance(name, str) or is_internal_attribute(name)
            for name in value
        ):
            raise ValueError(
                "Model documents cannot set reserved tracking fields."
            )
        native = getattr(fields, "decode_model", None)
        if native is not None:
            model = native(annotation, value, fields)
            if model is not None:
                return model
        hints = get_type_hints(annotation)
        decoded = {
            name: decode_json(item, hints.get(name, Any), fields)
            for name, item in value.items()
        }
        construct = getattr(fields, "construct", None)
        return (
            annotation(**decoded)
            if construct is None
            else construct(annotation, decoded)
        )
    return value
