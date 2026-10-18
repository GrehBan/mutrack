"""Conversion of plain containers into trackable containers.

This module is framework-agnostic. Concrete trackable container classes are
supplied through ``ContainerTypes``.

Three public operations are provided:

``prepare_value``
    Converts a value to its trackable representation and builds links inside
    newly-created containers, but does not link the returned root value to an
    external parent.

``prepare_values``
    Batch form of ``prepare_value``. All values share one wrapping context, so
    a plain container referenced by several values maps to one wrapper.

``wrap_value``
    Does the same conversion and additionally links the resulting root
    trackable value to the supplied parent.

Only exact built-in ``list``, ``dict`` and ``set`` instances are converted.
Subclasses are intentionally preserved.

Wrapping is not considered a mutation. Newly-created wrappers are populated
through built-in ``list``, ``dict`` and ``set`` methods, bypassing mutation
hooks and therefore avoiding ``changed()`` notifications.

Shared container references are preserved. Cyclic plain-container structures
are rejected because they would currently create cycles in the mutation
propagation graph.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Final, cast

from mutrack.tracking.graph.linking.transaction import LinkTransaction
from mutrack.tracking.parents import iter_ancestors
from mutrack.tracking.trackable.protocols import ITrackable, is_trackable
from mutrack.tracking.types import Key

_PLAIN_CONTAINER_TYPES: Final[frozenset[type]] = frozenset(
    {
        list,
        dict,
        set,
    }
)


@dataclass(frozen=True, slots=True)
class ContainerTypes:
    """Concrete trackable replacements for built-in containers.

    The classes are normally supplied by an adapter, for example the
    SQLAlchemy adapter.

    Every class must:

    - subclass the corresponding built-in container;
    - implement ``ITrackable``;
    - support construction without arguments.

    Attributes:
        list_type: Trackable subclass replacing exact built-in lists.
        dict_type: Trackable subclass replacing exact built-in
            dictionaries.
        set_type: Trackable subclass replacing exact built-in sets.
    """

    list_type: type[list[Any]]
    dict_type: type[dict[Any, Any]]
    set_type: type[set[Any]]

    def __post_init__(self) -> None:
        """Validate wrapper inheritance from built-in containers.

        Raises:
            TypeError: A wrapper type does not subclass its corresponding
                built-in container.
        """
        if not issubclass(self.list_type, list):
            raise TypeError("list_type must be a subclass of list.")

        if not issubclass(self.dict_type, dict):
            raise TypeError("dict_type must be a subclass of dict.")

        if not issubclass(self.set_type, set):
            raise TypeError("set_type must be a subclass of set.")


@dataclass(slots=True)
class _WrappedContainer:
    """Retain the original container, wrapper, and subtree height.

    Attributes:
        original: Original field value or plain container retained to
            preserve identity.
        wrapper: Trackable replacement corresponding to the retained
            plain container.
        height: Maximum subtree height, finalized before a completed
            memo entry is reused.
    """

    original: object
    wrapper: ITrackable

    height: int = 1


@dataclass(slots=True)
class _WrapContext:
    """State shared by one wrapping operation.

    Attributes:
        containers: Caller-supplied wrapper classes for exact plain
            containers.
        max_depth: Configured maximum graph or container nesting depth.
        links: Transaction receiving queued physical parent-child
            edges.
        wrapped: Identity memo retaining originals, wrappers, and
            completed subtree heights.
        in_progress: Identities on the active DFS path, used to detect
            actual cycles.
    """

    containers: ContainerTypes
    max_depth: int
    links: LinkTransaction

    wrapped: dict[int, _WrappedContainer] = field(
        default_factory=dict,
    )

    in_progress: set[int] = field(
        default_factory=set,
    )


class PreparationSession:
    """Prepare shared values with deferred graph links.

    The caller owns the supplied transaction and commits only after all
    preparation succeeds. Depth is absolute within that transaction's
    build; existing trackables remain unchanged and are not
    introspected here.
    """

    def __init__(
        self,
        *,
        containers: ContainerTypes,
        max_depth: int,
        links: LinkTransaction,
    ) -> None:
        """Bind a shared wrapping memo to the given transaction.

        Args:
            containers: Caller-supplied Trackable list, dictionary, and
                set types.
            max_depth: Maximum permitted absolute depth for newly wrapped
                containers.
            links: Shared transaction receiving deferred physical graph
                edges.
        """
        self._context = _create_context(containers, max_depth, links)
        self._failed = False

    def prepare_value(self, value: object, /, *, depth: int = 1) -> object:
        """Prepare a value and queue its internal container links.

        Args:
            value: Value to prepare while preserving shared references.
            depth: Current one-based depth within the graph or
                preparation operation.

        Returns:
            The prepared value, retaining identity for existing
            Trackables.

        Raises:
            RuntimeError: The session has failed or its link transaction is
                closed.
            ValueError: The depth is invalid, nesting exceeds the limit, or a
                plain-container cycle is found.
        """
        self._context.links.ensure_open()
        if self._failed:
            raise RuntimeError("Cannot reuse a failed preparation session.")
        try:
            if depth < 1:
                raise ValueError("Preparation depth must be positive.")
            return _prepare(value, depth=depth, context=self._context)
        except BaseException as error:
            self._failed = True
            self._context.links.rollback(error)
            raise


def validate_values(
    parent: ITrackable,
    values: Iterable[object],
    /,
) -> None:
    """Reject destination cycles before preparing any incoming values.

    Follow only exact containers that wrapping converts. Existing
    trackables are checked against the destination and its ancestors,
    without inspecting arbitrary object fields or invoking user
    descriptors.

    Args:
        parent: Trackable owner of the child reference.
        values: Incoming values processed by the operation.

    Raises:
        ValueError: A proposed Trackable child is the destination or one of its
            ancestors.
    """
    ancestors: dict[int, ITrackable] | None = None
    pending = list(values)
    seen: set[int] = set()

    while pending:
        value = pending.pop()

        if type(value) not in _PLAIN_CONTAINER_TYPES:
            if is_trackable(value):
                if ancestors is None:
                    ancestors = {
                        id(obj): obj for obj in iter_ancestors(parent)
                    }

                if id(value) in ancestors:
                    raise ValueError("Cannot create cyclic tracking links.")

            continue

        if id(value) in seen:
            continue

        seen.add(id(value))

        if isinstance(value, dict):
            pending.extend(value.values())
        else:
            pending.extend(cast("list[object] | set[object]", value))


def prepare_value(
    value: object,
    /,
    *,
    containers: ContainerTypes,
    max_depth: int,
) -> object:
    """Prepare a value for storage inside a trackable object.

    Exact built-in lists, dicts and sets are recursively replaced by
    the corresponding trackable classes.

    Existing ``ITrackable`` objects are returned unchanged.

    Internal parent-child links inside newly-created wrappers are
    established, but the returned root object is NOT linked to an
    external parent.

    This form is useful for collection mutations that later use
    ``reconcile_child_links``.

    Args:
        value: Value to prepare while preserving shared references.
        containers: Concrete trackable container classes.
        max_depth: Maximum nesting depth of plain containers. The
            supplied ``value`` has depth 1.

    Returns:
        Prepared value.

    Raises:
        ValueError: If ``max_depth`` is negative, nesting exceeds the
            limit or a cyclic plain-container structure is encountered.
        TypeError: If an adapter-provided wrapper does not implement
            ``ITrackable``.
    """
    if type(value) not in _PLAIN_CONTAINER_TYPES:
        return value

    links = LinkTransaction()
    session = PreparationSession(
        containers=containers,
        max_depth=max_depth,
        links=links,
    )
    result = session.prepare_value(value)
    links.commit()

    return result


def prepare_values(
    values: Iterable[object],
    /,
    *,
    containers: ContainerTypes,
    max_depth: int,
) -> list[object]:
    """Prepare several values for storage inside one trackable object.

    Equivalent to calling ``prepare_value`` for each value, except that
    all values share one wrapping context: a plain container reachable
    from several values is converted once and the wrapper is shared.
    Either all internal links are committed or none are.

    Args:
        values: Incoming values processed by the operation.
        containers: Caller-supplied Trackable list, dictionary, and set
            types.
        max_depth: Maximum permitted absolute depth for newly wrapped
            containers.

    Returns:
        Prepared values, in input order, as a new list.
    """
    result = list(values)

    if _PLAIN_CONTAINER_TYPES.isdisjoint(map(type, result)):
        return result

    links = LinkTransaction()
    session = PreparationSession(
        containers=containers,
        max_depth=max_depth,
        links=links,
    )

    for index, value in enumerate(result):
        result[index] = session.prepare_value(value)

    links.commit()

    return result


def wrap_value(
    parent: ITrackable,
    value: object,
    key: Key,
    /,
    *,
    containers: ContainerTypes,
    max_depth: int | None = None,
) -> object:
    """Prepare ``value`` and link the resulting root value to ``parent``.

    Existing trackable values are linked directly. Plain built-in
    containers are converted recursively and the resulting wrapper is
    linked.

    Non-trackable values are returned unchanged and do not create a
    graph edge.

    Args:
        parent: Trackable owner of the value.
        value: Value to prepare while preserving shared references.
        key: Location of the value inside ``parent``.
        containers: Concrete trackable container classes.
        max_depth: Maximum nesting depth of plain containers. Defaults
            to ``parent._max_depth_limit``.

    Returns:
        Prepared value.
    """
    if max_depth is None:
        max_depth = parent._max_depth_limit

    validate_values(parent, (value,))

    links = LinkTransaction()
    session = PreparationSession(
        containers=containers,
        max_depth=max_depth,
        links=links,
    )
    result = session.prepare_value(value)

    if is_trackable(result):
        links.add(parent, result, key)

    links.commit()

    return result


def _create_context(
    containers: ContainerTypes,
    max_depth: int,
    links: LinkTransaction,
    /,
) -> _WrapContext:
    """Create a wrapping context with a validated depth limit.

    Args:
        containers: Caller-supplied Trackable list, dictionary, and set
            types.
        max_depth: Maximum permitted absolute depth for newly wrapped
            containers.
        links: Shared transaction receiving deferred physical graph
            edges.

    Returns:
        A fresh wrapping context sharing the supplied link transaction.

    Raises:
        ValueError: The maximum depth is negative.
    """
    if max_depth < 0:
        raise ValueError("Wrapping max depth cannot be negative.")

    return _WrapContext(
        containers=containers,
        max_depth=max_depth,
        links=links,
    )


def _prepare(
    value: object,
    /,
    *,
    depth: int,
    context: _WrapContext,
) -> object:
    """Prepare one value without linking it to an external parent.

    Only exact built-in containers are converted; everything else,
    including existing trackables, is returned unchanged.

    Args:
        value: Value to prepare while preserving shared references.
        depth: Current one-based depth within the graph or preparation
            operation.
        context: State shared by the current traversal or wrapping
            operation.

    Returns:
        The original value or its memoized Trackable container wrapper.
    """
    if type(value) not in _PLAIN_CONTAINER_TYPES:
        return value

    return _wrap_container(
        value,
        depth,
        context,
    )


def _prepare_child(
    parent: ITrackable,
    value: object,
    key: Key,
    /,
    *,
    depth: int,
    context: _WrapContext,
) -> object:
    """Prepare a nested value and queue its link to ``parent``.

    Args:
        parent: Trackable owner of the child reference.
        value: Value to prepare while preserving shared references.
        key: Field name, container key, list index, or None for a set
            member.
        depth: Current one-based depth within the graph or preparation
            operation.
        context: State shared by the current traversal or wrapping
            operation.

    Returns:
        The prepared child value whose edge has been queued.
    """
    result = _prepare(
        value,
        depth=depth,
        context=context,
    )

    if is_trackable(result):
        _queue_link(
            parent,
            result,
            key,
            context,
        )

    return result


def _wrap_container(
    value: object,
    depth: int,
    context: _WrapContext,
    /,
) -> ITrackable:
    """Wrap an exact built-in ``list``, ``dict`` or ``set``.

    Args:
        value: Exact built-in container being converted to a Trackable wrapper.
        depth: Current one-based depth within the graph or preparation
            operation.
        context: State shared by the current traversal or wrapping
            operation.

    Returns:
        The new or memoized Trackable wrapper for the plain container.

    Raises:
        ValueError: The container is cyclic or its subtree exceeds the depth
            limit.
    """
    if depth > context.max_depth:
        raise ValueError(
            f"Container nesting exceeds max depth {context.max_depth}."
        )

    value_id = id(value)

    if value_id in context.in_progress:
        raise ValueError("Cannot wrap cyclic container structures.")

    known = context.wrapped.get(value_id)

    if known is not None:
        if depth + known.height - 1 > context.max_depth:
            raise ValueError(
                f"Container nesting exceeds max depth {context.max_depth}."
            )
        return known.wrapper

    context.in_progress.add(value_id)

    try:
        if isinstance(value, list):
            wrapped = _wrap_list(
                value,
                depth,
                context,
            )

        elif isinstance(value, dict):
            wrapped = _wrap_dict(
                value,
                depth,
                context,
            )

        else:
            wrapped = _wrap_set(
                cast("set[object]", value),
                depth,
                context,
            )

        children: Iterable[object] = (
            value.values()
            if isinstance(value, dict)
            else cast("list[object] | set[object]", value)
        )
        context.wrapped[value_id].height = 1 + max(
            (
                context.wrapped[id(child)].height
                for child in children
                if type(child) in _PLAIN_CONTAINER_TYPES
            ),
            default=0,
        )
        return wrapped

    finally:
        context.in_progress.remove(value_id)


def _wrap_list(
    value: list[object],
    depth: int,
    context: _WrapContext,
    /,
) -> ITrackable:
    """Create and populate a trackable list wrapper.

    Args:
        value: Exact built-in container being converted to a Trackable wrapper.
        depth: Current one-based depth within the graph or preparation
            operation.
        context: State shared by the current traversal or wrapping
            operation.

    Returns:
        The populated Trackable list wrapper.
    """
    wrapped = context.containers.list_type()

    trackable = _remember(
        value,
        wrapped,
        context,
    )

    for index, item in enumerate(value):
        prepared = _prepare_child(
            trackable,
            item,
            index,
            depth=depth + 1,
            context=context,
        )

        list.append(
            wrapped,
            prepared,
        )

    return trackable


def _wrap_dict(
    value: dict[object, object],
    depth: int,
    context: _WrapContext,
    /,
) -> ITrackable:
    """Create and populate a trackable dict wrapper.

    Dict keys are intentionally preserved as-is. Only values
    participate in recursive wrapping and graph linking.

    Args:
        value: Exact built-in container being converted to a Trackable wrapper.
        depth: Current one-based depth within the graph or preparation
            operation.
        context: State shared by the current traversal or wrapping
            operation.

    Returns:
        The populated Trackable dictionary wrapper.
    """
    wrapped = context.containers.dict_type()

    trackable = _remember(
        value,
        wrapped,
        context,
    )

    for key, item in value.items():
        prepared = _prepare_child(
            trackable,
            item,
            key,
            depth=depth + 1,
            context=context,
        )

        dict.__setitem__(
            wrapped,
            key,
            prepared,
        )

    return trackable


def _wrap_set(
    value: set[object],
    depth: int,
    context: _WrapContext,
    /,
) -> ITrackable:
    """Create and populate a trackable set wrapper.

    Set members do not have stable positional keys and therefore use
    ``None`` as their graph key.

    Args:
        value: Exact built-in container being converted to a Trackable wrapper.
        depth: Current one-based depth within the graph or preparation
            operation.
        context: State shared by the current traversal or wrapping
            operation.

    Returns:
        The populated Trackable set wrapper.
    """
    wrapped = context.containers.set_type()

    trackable = _remember(
        value,
        wrapped,
        context,
    )

    for item in value:
        prepared = _prepare_child(
            trackable,
            item,
            None,
            depth=depth + 1,
            context=context,
        )

        set.add(
            wrapped,
            prepared,
        )

    return trackable


def _remember(
    original: object,
    wrapper: object,
    context: _WrapContext,
    /,
) -> ITrackable:
    """Remember a wrapper before descending into its contents.

    Args:
        original: Original object retained to preserve identity during
            preparation.
        wrapper: New Trackable container replacing an exact plain
            container.
        context: State shared by the current traversal or wrapping
            operation.

    Returns:
        The validated Trackable wrapper retained in the identity memo.

    Raises:
        TypeError: The supplied wrapper does not implement ITrackable.
    """
    if not is_trackable(wrapper):
        raise TypeError(
            f"{type(wrapper).__qualname__} does not implement ITrackable."
        )

    context.wrapped[id(original)] = _WrappedContainer(
        original=original,
        wrapper=wrapper,
    )

    return wrapper


def _queue_link(
    parent: ITrackable,
    child: ITrackable,
    key: Key,
    context: _WrapContext,
    /,
) -> None:
    """Queue a container edge in the shared link transaction.

    Args:
        parent: Trackable owner of the child reference.
        child: Trackable child participating in the parent
            relationship.
        key: Field name, container key, list index, or None for a set
            member.
        context: State shared by the current traversal or wrapping
            operation.
    """
    context.links.add(parent, child, key)


__all__ = (
    "ContainerTypes",
    "PreparationSession",
    "prepare_value",
    "prepare_values",
    "wrap_value",
)
