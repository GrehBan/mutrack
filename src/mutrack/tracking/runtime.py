"""Enable framework-neutral field and container mutation tracking."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import cast
from weakref import WeakSet

from mutrack.internal.attributes import (
    CHANGE_SUPPRESS_LEVEL_STORE,
    PARENTS_STORE,
    PENDING_CHANGE_STORE,
    RUNTIME_STORE,
    STATE_STORE,
)
from mutrack.internal.object_access import (
    delete_stored_field,
    get_instance_dict,
    raw_getattr,
    raw_setattr,
    set_stored_field,
)
from mutrack.introspection.inspection import is_internal_attribute
from mutrack.tracking.access import get_state
from mutrack.tracking.build import build_graph, prepare_graph_values
from mutrack.tracking.factory import create_parents, create_state
from mutrack.tracking.field_access import FieldAccess
from mutrack.tracking.graph.traversal import iter_children
from mutrack.tracking.parents import get_parents_snapshot
from mutrack.tracking.trackable.protocols import ITrackable, is_trackable
from mutrack.tracking.wrapping import ContainerTypes, validate_values


@dataclass(frozen=True)
class TrackingOptions:
    """Configure field discovery and container preparation for live models.

    Attributes:
        fields: Framework-specific stored field access.
        containers: Mutation-aware container implementations.
        max_depth: Maximum depth for model and incoming-value preparation.
    """

    fields: FieldAccess
    containers: ContainerTypes
    max_depth: int


@dataclass
class _Runtime:
    """Store per-instance configuration and a reentrant assignment guard."""

    options: TrackingOptions
    active: bool = False


_INSTRUMENTED: WeakSet[type] = WeakSet()


def runtime_options(obj: object, /) -> TrackingOptions | None:
    """Return live tracking options without initializing bookkeeping.

    Args:
        obj: Model or container whose configuration is requested.

    Returns:
        Existing options, or None for an unconfigured object.
    """
    state = raw_getattr(obj, RUNTIME_STORE, None)
    return state.options if isinstance(state, _Runtime) else None


def configure_graph(
    values: Iterable[object], options: TrackingOptions
) -> None:
    """Enable hooks on reachable models and configure mutation containers.

    Args:
        values: Prepared graph roots whose identities remain unchanged.
        options: Shared field and container configuration.

    Raises:
        ValueError: An existing object uses incompatible tracking options.
    """
    pending = list(values)
    seen: set[int] = set()
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if not is_trackable(value):
            if isinstance(value, (list, dict, set)):
                pending.extend(child for _, child in iter_children(value))
            continue
        token = get_state(value, None)
        if token is not None and token.obj() is not value:
            namespace = get_instance_dict(value)
            if namespace is not None:
                raw_setattr(value, "__dict__", dict(namespace))
            raw_setattr(value, STATE_STORE, create_state(value))
            raw_setattr(value, PARENTS_STORE, create_parents())
            raw_setattr(value, CHANGE_SUPPRESS_LEVEL_STORE, 0)
            raw_setattr(value, PENDING_CHANGE_STORE, False)
            raw_setattr(value, RUNTIME_STORE, None)
            capture = getattr(options.fields, "checkpoint", None)
            restore = getattr(options.fields, "restore_checkpoint", None)
            if capture is not None and restore is not None:
                restore(value, capture(value))
        old = runtime_options(value)
        if old is not None and old != options:
            raise ValueError(
                "Shared models require compatible tracking options."
            )
        if old is None:
            raw_setattr(value, RUNTIME_STORE, _Runtime(options))
        if isinstance(value, (list, dict, set)):
            pending.extend(child for _, child in iter_children(value))
        elif options.fields.supports(value):
            _instrument(type(value))
            pending.extend(
                child for _, child in options.fields.iter_fields(value)
            )


def prepare_runtime_values(
    parent: ITrackable, values: Iterable[object], /
) -> list[object] | None:
    """Prepare nested models when a configured container receives values.

    Args:
        parent: Destination container providing runtime options.
        values: Materialized incoming values to wrap and inspect.

    Returns:
        Prepared values, or None when ordinary wrapping should be used.
    """
    options = runtime_options(parent)
    if options is None:
        return None
    materialized = list(values)
    validate_values(parent, materialized)
    configure_graph(materialized, options)
    prepared = prepare_graph_values(
        materialized,
        containers=options.containers,
        fields=options.fields,
        max_depth=options.max_depth - _ancestor_depth(parent),
    )
    configure_graph(prepared, options)
    return prepared


def _ancestor_depth(obj: ITrackable, /) -> int:
    """Find the longest live configured path from a document root to an object.

    Args:
        obj: Model or container receiving a runtime mutation.

    Returns:
        One-based object depth, excluding external ORM observers.
    """
    pending = [(obj, 1)]
    depths = {id(obj): 1}
    deepest = 1
    while pending:
        child, depth = pending.pop()
        deepest = max(deepest, depth)
        for token, _ in get_parents_snapshot(child):
            parent = token.obj()
            if parent is None or runtime_options(parent) is None:
                continue
            next_depth = depth + 1
            if next_depth > depths.get(id(parent), 0):
                depths[id(parent)] = next_depth
                pending.append((parent, next_depth))
    return deepest


def _instrument(cls: type, /) -> None:
    """Wrap native setters while keeping inactive model instances native.

    Args:
        cls: User model class whose instances explicitly enable tracking.
    """
    if cls in _INSTRUMENTED:
        return
    assign = cast(Callable[[object, str, object], None], cls.__setattr__)
    remove = cast(Callable[[object, str], None], cls.__delattr__)

    def tracked_set(obj: object, name: str, value: object) -> None:
        """Delegate validation and reconcile the resulting stored fields.

        Args:
            obj: Model receiving an assignment.
            name: Requested attribute name.
            value: Incoming value before native validation or conversion.
        """
        _mutate(obj, name, lambda: assign(obj, name, value))

    def tracked_delete(obj: object, name: str) -> None:
        """Delegate deletion and remove links for unavailable fields.

        Args:
            obj: Model receiving a deletion.
            name: Requested attribute name.
        """
        _mutate(obj, name, lambda: remove(obj, name))

    setattr(cls, "__setattr__", tracked_set)
    setattr(cls, "__delattr__", tracked_delete)
    _INSTRUMENTED.add(cls)


def _mutate(obj: object, name: str, operation: Callable[[], None]) -> None:
    """Run a native field operation and reconcile validated values atomically.

    Args:
        obj: Configured model, or an untouched instance of the same class.
        name: Attribute whose native mutation was requested.
        operation: Native assignment, converter, validator, or deletion call.
    """
    state = raw_getattr(obj, RUNTIME_STORE, None)
    if (
        not isinstance(state, _Runtime)
        or state.active
        or is_internal_attribute(name)
    ):
        operation()
        return
    model = cast(ITrackable, obj)
    options = state.options
    before = dict(options.fields.iter_fields(model))
    checkpoint = getattr(options.fields, "checkpoint", lambda _: None)(model)
    state.active = True
    try:
        operation()
        after_native = dict(options.fields.iter_fields(model))
        if name not in before and name not in after_native:
            return
        if before.keys() == after_native.keys() and all(
            value is after_native[key] for key, value in before.items()
        ):
            return
        validate_values(model, after_native.values())
        configure_graph([model], options)
        build_graph(
            model,
            containers=options.containers,
            fields=options.fields,
            max_depth=options.max_depth - _ancestor_depth(model) + 1,
        )
        configure_graph([model], options)
    except BaseException as error:
        _restore(model, before, options.fields, error)
        restore = getattr(options.fields, "restore_checkpoint", None)
        if restore is not None:
            try:
                restore(model, checkpoint)
            except BaseException as failure:
                error.add_note(f"Model metadata rollback failed: {failure!r}")
        raise
    finally:
        state.active = False
    after = dict(options.fields.iter_fields(model))
    for key, old in before.items():
        if old is not after.get(key) and is_trackable(old):
            model._state.unlink(old, key)
    model.changed()


def _restore(
    model: ITrackable,
    before: dict[str, object],
    fields: FieldAccess,
    error: BaseException,
) -> None:
    """Restore field identities without invoking normal mutation hooks.

    Args:
        model: Model whose operation failed.
        before: Available stored fields before the native operation.
        fields: Adapter discovering the currently available fields.
        error: Original exception receiving any restoration failure notes.
    """
    current = dict(fields.iter_fields(model))
    for name in current.keys() - before.keys():
        try:
            delete_stored_field(model, name)
        except BaseException as failure:
            error.add_note(f"Model field rollback failed: {failure!r}")
    for name, value in before.items():
        try:
            set_stored_field(model, name, value, create=True)
        except BaseException as failure:
            error.add_note(f"Model field rollback failed: {failure!r}")
