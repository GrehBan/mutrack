"""Track nested mutations in SQLAlchemy list containers."""

from __future__ import annotations

import operator
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Self, SupportsIndex, TypeVar, cast

from sqlalchemy.ext.mutable import MutableList

from mutrack.adapters.sqlalchemy.collections.base import (
    _SQLAlchemyTrackableCollection,
)
from mutrack.tracking.graph.linking.collections import (
    ChildLinksSnapshot,
    LinkEntry,
    add_child_links,
    iter_trackable_items,
    link_entries,
    reconcile_child_links,
    snapshot_child_links,
    snapshot_sequence_links,
    unlink_entries,
)
from mutrack.tracking.parents import capture_parent_links, get_parents_snapshot
from mutrack.tracking.suppression import batch_changes
from mutrack.tracking.trackable.protocols import is_trackable

T = TypeVar("T")


def _native_index(index: SupportsIndex, /) -> int:
    """Resolve an integer within the native signed index range.

    Args:
        index: Integer-like position accepted by insertion and pop.

    Returns:
        The resolved native-sized integer.

    Raises:
        OverflowError: The integer cannot fit a native signed index.
    """
    resolved = operator.index(index)
    if resolved < -sys.maxsize - 1 or resolved > sys.maxsize:
        raise OverflowError("Python int too large to convert to C ssize_t")
    return resolved


def _resolve_slice(index: slice, /) -> slice:
    """Resolve each slice component once without normalizing sentinels.

    Args:
        index: Slice whose bounds can provide stateful index conversion.

    Returns:
        A slice containing only integers and None.

    Raises:
        ValueError: The resolved slice step is zero.
    """
    step = None if index.step is None else operator.index(index.step)
    if step == 0:
        raise ValueError("slice step cannot be zero")
    start = None if index.start is None else operator.index(index.start)
    stop = None if index.stop is None else operator.index(index.stop)
    return slice(start, stop, step)


class SQLAlchemyTrackableList(
    _SQLAlchemyTrackableCollection,
    MutableList[T],
):
    """SQLAlchemy MutableList integrated with the mutrack graph.

    Every direct trackable child is linked under its current index.

    New values are prepared (plain containers wrapped) and linked under
    their final indices *before* the list is physically changed, so a
    failure while wrapping or linking leaves both the list and the
    graph untouched. Existing values are never re-wrapped; when an
    operation shifts them, only the affected index range is snapshotted
    and the graph is reconciled afterwards.

    Raw ``list`` methods are used internally to avoid the notification
    hooks implemented by SQLAlchemy's ``MutableList``. Each public
    mutation emits exactly one ``changed()`` notification; operations
    that provably leave the list unchanged (e.g. ``extend([])``) emit
    none.

    Repetition allocates through the built-in first, then links its new
    indices transactionally; a linking failure truncates the added
    suffix.
    """

    def __init__(
        self,
        iterable: Iterable[T] = (),
        /,
    ) -> None:
        """Prepare initial contents and links without notifying.

        Args:
            iterable: Source values materialized before the operation.
        """
        values = self._prepare_values(iterable)

        if self:
            unlink_entries(
                self,
                list(iter_trackable_items(self)),
            )

        link_entries(
            self,
            iter_trackable_items(values),
        )

        list.__init__(
            self,
            values,
        )

    def _snapshot(
        self,
        start: int = 0,
        stop: int | None = None,
        /,
    ) -> ChildLinksSnapshot:
        """Snapshot direct trackable children in ``[start, stop)``.

        Args:
            start: Inclusive starting position or index offset.
            stop: Exclusive ending position, or None for the remaining
                suffix.

        Returns:
            Tracked child identities and keys for the selected list
            range.
        """
        return snapshot_sequence_links(
            self[start:stop],
            start,
        )

    def _rewrite(
        self,
        operation: Callable[[], object],
        start: int,
        stop: int | None = None,
        new_entries: Sequence[LinkEntry] = (),
        /,
    ) -> None:
        """Run a physical mutation confined to positions ``>= start``.

        ``stop`` may be given when the operation does not shift values,
        so only ``[start, stop)`` needs reconciling.

        ``new_entries`` are the trackable new values under their final
        indices. They are linked before ``operation`` runs and counted
        as existing links, so reconciliation never links them twice.

        Args:
            operation: Callback performing the physical list mutation.
            start: Inclusive starting position or index offset.
            stop: Exclusive ending position, or None for the remaining
                suffix.
            new_entries: Prepared child references under their final
                list indices.
        """
        before = self._snapshot(
            start,
            stop,
        )

        created = link_entries(
            self,
            new_entries,
        )

        add_child_links(
            before,
            new_entries,
        )

        try:
            operation()

        except Exception:
            unlink_entries(
                self,
                created,
            )
            raise

        reconcile_child_links(
            self,
            before,
            self._snapshot(
                start,
                stop,
            ),
        )

        self.changed()

    @staticmethod
    def _normalize_existing_index(
        index: SupportsIndex,
        length: int,
        /,
    ) -> int:
        """Normalize an index that must already exist.

        Negative indices are resolved relative to the current length.

        Args:
            index: Integer-like list position to normalize.
            length: Current sequence length used to normalize an index.

        Returns:
            The nonnegative index of an existing list item.

        Raises:
            IndexError: The requested position is outside the existing
                list.
        """
        normalized = operator.index(index)

        if normalized < 0:
            normalized += length

        if normalized < 0 or normalized >= length:
            raise IndexError("list index out of range")

        return normalized

    @staticmethod
    def _normalize_insert_index(
        index: SupportsIndex,
        length: int,
        /,
    ) -> int:
        """Normalize an index using ``list.insert`` semantics.

        Negative positions are resolved relative to the length and
        clamped like list.insert.

        Args:
            index: Integer-like list position to normalize.
            length: Current sequence length used to normalize an index.

        Returns:
            The insertion index clamped to valid list boundaries.

        Raises:
            OverflowError: The position does not fit a native signed index.
        """
        normalized = _native_index(index)

        if normalized < 0:
            return max(
                0,
                length + normalized,
            )

        return min(
            normalized,
            length,
        )

    def append(
        self,
        x: T,
    ) -> None:
        """Append a value, link its final index, and notify.

        Args:
            x: Value to prepare and store in the list.
        """
        value = self._prepare_value(x)

        if is_trackable(value):
            self._state.link(
                value,
                len(self),
            )

        list.append(
            self,
            value,
        )

        self.changed()

    def extend(
        self,
        x: Iterable[T],
    ) -> None:
        """Prepare incoming values together, append, and notify.

        Args:
            x: Iterable of values prepared together before appending.
        """
        values = self._prepare_values(x)

        if not values:
            return

        link_entries(
            self,
            iter_trackable_items(
                values,
                len(self),
            ),
        )

        list.extend(
            self,
            values,
        )

        self.changed()

    def __setitem__(
        self,
        index: SupportsIndex | slice,
        value: T | Iterable[T],
    ) -> None:
        """Store replacement values while keeping child links consistent.

        Args:
            index: Integer-like position or slice selecting list
                contents.
            value: Replacement item, or an iterable for slice assignment.
        """
        if isinstance(index, slice):
            self._set_slice(
                index,
                cast(Iterable[T], value),
            )
            return

        position = self._normalize_existing_index(
            index,
            len(self),
        )

        new = self._prepare_value(cast(T, value))
        old = list.__getitem__(
            self,
            position,
        )

        if new is not old and is_trackable(new):
            self._state.link(
                new,
                position,
            )

        list.__setitem__(
            self,
            position,
            new,
        )

        if new is not old and is_trackable(old):
            self._state.unlink(
                old,
                position,
            )

        self.changed()

    def _set_slice(
        self,
        index: slice,
        values: Iterable[T],
        /,
    ) -> None:
        """Prepare slice replacements and reconcile affected child indices.

        Args:
            index: Slice selecting the positions to replace or delete.
            values: Incoming values processed by the operation.

        Raises:
            ValueError: The input would violate a cycle, depth, size,
                or state invariant.
        """
        index = _resolve_slice(index)
        replacement = self._prepare_values(values)

        start, stop, step = index.indices(len(self))

        if step == 1:
            removed = max(
                0,
                stop - start,
            )

            if not removed and not replacement:
                return

            new_entries = list(
                iter_trackable_items(
                    replacement,
                    start,
                )
            )

            self._rewrite(
                lambda: list.__setitem__(self, index, replacement),
                start,
                start + removed if removed == len(replacement) else None,
                new_entries,
            )
            return

        positions = range(
            start,
            stop,
            step,
        )

        if len(replacement) != len(positions):
            raise ValueError(
                "attempt to assign sequence of size "
                f"{len(replacement)} to extended slice of size "
                f"{len(positions)}"
            )

        if not positions:
            return

        new_entries = [
            (position, item)
            for position, item in zip(positions, replacement)
            if is_trackable(item)
        ]

        before = snapshot_child_links(
            zip(
                positions,
                self[index],
            )
        )

        created = link_entries(
            self,
            new_entries,
        )

        add_child_links(
            before,
            new_entries,
        )

        try:
            list.__setitem__(
                self,
                index,
                replacement,
            )

        except Exception:
            unlink_entries(
                self,
                created,
            )
            raise

        reconcile_child_links(
            self,
            before,
            snapshot_child_links(
                zip(
                    positions,
                    self[index],
                )
            ),
        )

        self.changed()

    def insert(
        self,
        i: SupportsIndex,
        x: T,
    ) -> None:
        """Insert a prepared value and reconcile shifted child indices.

        Args:
            i: Integer-like insertion position, clamped to list bounds.
            x: Value to prepare and store in the list.
        """
        position = self._normalize_insert_index(
            i,
            len(self),
        )
        value = self._prepare_value(x)

        new_entries: list[LinkEntry] = (
            [(position, value)] if is_trackable(value) else []
        )

        self._rewrite(
            lambda: list.insert(self, position, value),
            position,
            None,
            new_entries,
        )

    def __delitem__(
        self,
        index: SupportsIndex | slice,
    ) -> None:
        """Delete stored values and remove or reconcile their child links.

        Args:
            index: Integer-like position or slice selecting list
                contents.
        """
        if isinstance(index, slice):
            self._del_slice(index)
            return

        self._del_position(
            self._normalize_existing_index(
                index,
                len(self),
            )
        )

    def _del_position(
        self,
        position: int,
        /,
    ) -> None:
        """Delete one position and reconcile the shifted suffix.

        Args:
            position: Normalized position in the current list.
        """
        self._rewrite(
            lambda: list.__delitem__(self, position),
            position,
        )

    def _del_slice(
        self,
        index: slice,
        /,
    ) -> None:
        """Delete selected positions and reconcile the affected suffix.

        Args:
            index: Slice selecting the positions to replace or delete.
        """
        index = _resolve_slice(index)
        positions = range(*index.indices(len(self)))

        if not positions:
            return

        self._rewrite(
            lambda: list.__delitem__(self, index),
            min(positions[0], positions[-1]),
        )

    def pop(
        self,
        *arg: SupportsIndex,
    ) -> T:
        """Pop an indexed item and reconcile shifted child keys.

        Args:
            *arg: Positional arguments forwarded to the built-in
                collection operation.

        Returns:
            The stored value removed from the list.

        Raises:
            TypeError: More than one positional index is supplied.
            OverflowError: The position does not fit a native signed index.
            IndexError: The requested position is outside the existing
                list.
        """
        if len(arg) > 1:
            raise TypeError(f"pop expected at most 1 argument, got {len(arg)}")

        resolved = _native_index(arg[0] if arg else -1)
        if not self:
            raise IndexError("pop from empty list")

        position = self._normalize_existing_index(
            resolved,
            len(self),
        )

        result: T = list.__getitem__(
            self,
            position,
        )

        self._del_position(position)

        return result

    def remove(
        self,
        i: T,
    ) -> None:
        """Remove a matching value and unlink the stored representative.

        Args:
            i: Equality probe locating the first stored value to remove.
        """
        self._del_position(list.index(self, i))

    def clear(self) -> None:
        """Clear contents and links, notifying on change."""
        if not self:
            return

        entries = list(iter_trackable_items(self))

        list.clear(self)

        unlink_entries(
            self,
            entries,
        )

        self.changed()

    def reverse(self) -> None:
        """Reverse list contents and reconcile child indices."""
        if len(self) < 2:
            return

        self._rewrite(
            lambda: list.reverse(self),
            0,
        )

    def sort(
        self,
        **kw: Any,
    ) -> None:
        """Sort contents and repair links touched by callbacks.

        Native sorting temporarily hides list storage and discards
        callback-added values. Repair considers original, final, and
        captured children using actual current graph keys, including on
        failure.

        Args:
            **kw: Keyword arguments forwarded to the built-in
                collection operation.
        """
        length = len(self)
        before = self._snapshot()
        state = self._state

        with batch_changes(self), capture_parent_links(state) as touched:
            try:
                list.sort(
                    self,
                    **kw,
                )
            finally:
                after = self._snapshot()
                children = {
                    identity: entry.child
                    for identity, entry in (before | after).items()
                }
                children.update(touched)

                actual = snapshot_child_links(
                    (key, child)
                    for child in children.values()
                    for parent_state, keys in get_parents_snapshot(child)
                    if parent_state is state
                    for key in keys
                )
                reconcile_child_links(self, actual, after)

                if length >= 2:
                    self.changed()

    def __imul__(
        self,
        n: SupportsIndex,
    ) -> Self:
        """Repeat contents with bounds checks and link rollback.

        Reject counts outside the native index range before mutation.
        Native allocation precedes repeated link expansion; a link
        failure truncates the appended suffix and rolls back new keys.

        Args:
            n: Integer-like repetition count.

        Returns:
            This list after repetition, preserving its object identity.

        Raises:
            OverflowError: The repetition count does not fit a native
                index-sized integer.
        """
        count = operator.index(n)

        if count < -sys.maxsize - 1 or count > sys.maxsize:
            raise OverflowError("cannot fit 'int' into an index-sized integer")

        if count <= 0:
            self.clear()
            return self

        length = len(self)

        if count == 1 or not length:
            return self

        base = list(iter_trackable_items(self))

        list.__imul__(self, count)

        try:
            if base:
                link_entries(
                    self,
                    (
                        (index + length * repeat, child)
                        for repeat in range(1, count)
                        for index, child in base
                    ),
                )
        except Exception:
            list.__delitem__(self, slice(length, None))
            raise

        self.changed()

        return self
