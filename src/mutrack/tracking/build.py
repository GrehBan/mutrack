"""Framework-neutral orchestration of initial Trackable model graphs."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from mutrack.tracking.field_access import FieldAccess
from mutrack.tracking.graph.linking.transaction import LinkTransaction
from mutrack.tracking.graph.traversal import iter_children
from mutrack.tracking.trackable.protocols import ITrackable, is_trackable
from mutrack.tracking.types import Key
from mutrack.tracking.wrapping import ContainerTypes, PreparationSession


@dataclass(frozen=True, slots=True)
class _Assignment:
    """Record an original model field value for reverse-order restoration.

    Attributes:
        obj: Model whose stored field was replaced.
        name: Stored field name used for replacement and restoration.
        original: Original field value or plain container retained to
            preserve identity.
    """

    obj: ITrackable
    name: str
    original: object


@dataclass(frozen=True, slots=True)
class _BuiltNode:
    """Retain a completed graph node and its maximum subtree height.

    Attributes:
        obj: Object retained strongly while its identity is used as a
            memo key.
        height: Maximum subtree height, finalized before a completed
            memo entry is reused.
    """

    obj: ITrackable
    height: int


@dataclass(slots=True)
class _Frame:
    """Track a model DFS frame, its child iterator, and subtree height.

    Attributes:
        obj: Graph node currently being traversed.
        depth: One-based depth of the active graph node.
        children: Iterator of direct child locations and Trackable values.
        height: Maximum subtree height, finalized before a completed
            memo entry is reused.
    """

    obj: ITrackable
    depth: int
    children: Iterator[tuple[Key, ITrackable]]
    height: int = 1


@dataclass(slots=True)
class _BuildContext:
    """Share field access and rollback state across a build.

    Attributes:
        fields: Adapter providing model field access and raw
            replacement.
        session: Shared container preparation session for the entire
            graph build.
        links: Transaction receiving queued physical parent-child
            edges.
        max_depth: Configured maximum graph or container nesting depth.
        assignments: Field replacement journal replayed in reverse
            during rollback.
        built: Completed graph nodes and their subtree heights, indexed
            by identity.
        in_progress: Identities on the active DFS path, used to detect
            actual cycles.
    """

    fields: FieldAccess
    session: PreparationSession
    links: LinkTransaction
    max_depth: int
    assignments: list[_Assignment] = field(default_factory=list)
    built: dict[int, _BuiltNode] = field(default_factory=dict)
    in_progress: set[int] = field(default_factory=set)


def build_graph(
    root: ITrackable,
    /,
    *,
    containers: ContainerTypes,
    fields: FieldAccess,
    max_depth: int | None = None,
) -> None:
    """Prepare and link a model graph without notifications.

    Root depth is one. Every Trackable child adds a level; scalar
    values do not. Shared nodes are built once and checked on every
    incoming path. Unsupported nested Trackables are opaque leaves.
    Existing Trackable containers are scanned but never re-wrapped or
    rewritten.

    All edges, including newly wrapped container internals, commit
    together. On failure, new links and field replacements roll back.
    This constructs an initial graph; it does not remove stale edges
    from runtime edits.

    Args:
        root: Trackable root whose initial graph is constructed.
        containers: Caller-supplied Trackable list, dictionary, and set
            types.
        fields: Field adapter defining stored model access and raw
            replacement.
        max_depth: Maximum permitted nesting depth, or the root limit
            when omitted.

    Raises:
        TypeError: The root is not a supported Trackable model.
        ValueError: The depth limit is negative, a cycle is found, or graph
            depth exceeds the limit.
    """
    if not is_trackable(root):
        raise TypeError("Graph root must implement ITrackable.")
    limit = root._max_depth_limit if max_depth is None else max_depth
    if limit < 0:
        raise ValueError("Graph max depth cannot be negative.")
    if isinstance(root, (list, dict, set)) or not fields.supports(root):
        raise TypeError("Graph root must be a supported Trackable model.")

    links = LinkTransaction()
    context = _BuildContext(
        fields=fields,
        session=PreparationSession(
            containers=containers, max_depth=limit, links=links
        ),
        links=links,
        max_depth=limit,
    )
    try:
        _traverse(root, context)
        links.commit()
    except BaseException as error:
        links.rollback(error)
        _restore_fields(context, error)
        raise


def prepare_graph_values(
    values: Iterable[object],
    /,
    *,
    containers: ContainerTypes,
    fields: FieldAccess,
    max_depth: int,
) -> list[object]:
    """Prepare incoming values and nested models in one graph transaction.

    Args:
        values: Incoming values sharing one container identity memo.
        containers: Concrete Trackable container implementations.
        fields: Adapter used to discover nested model fields.
        max_depth: Maximum depth measured from each incoming value.

    Returns:
        Prepared values with nested model graphs connected.
    """
    links = LinkTransaction()
    context = _BuildContext(
        fields,
        PreparationSession(
            containers=containers, max_depth=max_depth, links=links
        ),
        links,
        max_depth,
    )
    try:
        prepared = [context.session.prepare_value(value) for value in values]
        for value in prepared:
            if is_trackable(value) and id(value) not in context.built:
                _traverse(value, context)
        links.commit()
    except BaseException as error:
        links.rollback(error)
        _restore_fields(context, error)
        raise
    return prepared


def _children(
    obj: ITrackable, depth: int, context: _BuildContext, /
) -> Iterator[tuple[Key, ITrackable]]:
    """Prepare model fields and yield their direct Trackable edges.

    Args:
        obj: Object whose stored state or fields are accessed.
        depth: Current one-based depth within the graph or preparation
            operation.
        context: State shared by the current traversal or wrapping
            operation.

    Yields:
        A field name or container key paired with its Trackable child.
    """
    if isinstance(obj, (list, dict, set)):
        for key, value in tuple(iter_children(obj)):
            if is_trackable(value):
                yield key, value
    elif context.fields.supports(obj):
        for name, value in tuple(context.fields.iter_fields(obj)):
            prepared = context.session.prepare_value(value, depth=depth + 1)
            if prepared is not value:
                context.assignments.append(_Assignment(obj, name, value))
                context.fields.set_field(obj, name, prepared)
            if is_trackable(prepared):
                yield name, prepared


def _check_depth(depth: int, height: int, limit: int, /) -> None:
    """Reject a subtree that exceeds the available graph depth.

    Args:
        depth: Current one-based depth within the graph or preparation
            operation.
        height: Maximum subtree height, counting the subtree root as
            one.
        limit: Maximum permitted graph depth.

    Raises:
        ValueError: The subtree would exceed the graph depth limit.
    """
    if depth + height - 1 > limit:
        raise ValueError(f"Graph nesting exceeds max depth {limit}.")


def _frame(obj: ITrackable, depth: int, context: _BuildContext, /) -> _Frame:
    """Create a DFS frame and mark its node as active.

    Args:
        obj: Object whose stored state or fields are accessed.
        depth: Current one-based depth within the graph or preparation
            operation.
        context: State shared by the current traversal or wrapping
            operation.

    Returns:
        An active DFS frame positioned at the supplied graph depth.
    """
    _check_depth(depth, 1, context.max_depth)
    context.in_progress.add(id(obj))
    return _Frame(obj, depth, _children(obj, depth, context))


def _traverse(root: ITrackable, context: _BuildContext, /) -> None:
    """Traverse model and container edges iteratively.

    Args:
        root: Trackable root whose initial graph is constructed.
        context: State shared by the current traversal or wrapping
            operation.

    Raises:
        ValueError: A cycle is found in the model or container graph.
    """
    stack = [_frame(root, 1, context)]
    while stack:
        frame = stack[-1]
        try:
            key, child = next(frame.children)
        except StopIteration:
            context.in_progress.remove(id(frame.obj))
            context.built[id(frame.obj)] = _BuiltNode(frame.obj, frame.height)
            stack.pop()
            if stack:
                stack[-1].height = max(stack[-1].height, frame.height + 1)
            continue

        context.links.add(frame.obj, child, key)
        if id(child) in context.in_progress:
            raise ValueError("Cannot build cyclic model graphs.")
        known = context.built.get(id(child))
        if known is not None:
            _check_depth(frame.depth + 1, known.height, context.max_depth)
            frame.height = max(frame.height, known.height + 1)
        else:
            stack.append(_frame(child, frame.depth + 1, context))


def _restore_fields(context: _BuildContext, error: BaseException, /) -> None:
    """Restore original field values in reverse replacement order.

    Args:
        context: State shared by the current traversal or wrapping
            operation.
        error: Original failure to annotate if rollback also fails.
    """
    for assignment in reversed(context.assignments):
        try:
            context.fields.set_field(
                assignment.obj, assignment.name, assignment.original
            )
        except BaseException as failure:
            error.add_note(
                f"Restoring field {assignment.name!r} on "
                f"{type(assignment.obj).__name__} failed: {failure!r}"
            )
