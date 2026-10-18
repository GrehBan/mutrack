"""Track nested mutations in SQLAlchemy set containers."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import chain
from typing import Any, TypeVar, cast

from sqlalchemy.ext.mutable import MutableSet

from mutrack.adapters.sqlalchemy.base import _SQLAlchemyTrackableBase
from mutrack.internal.attributes import TRACKED_MEMBERS_STORE
from mutrack.internal.object_access import raw_getattr, raw_setattr
from mutrack.tracking.graph.linking.collections import (
    iter_trackable_items,
    link_entries,
    unlink_entries,
)
from mutrack.tracking.runtime import prepare_runtime_values
from mutrack.tracking.trackable.protocols import ITrackable, is_trackable

T = TypeVar("T")


_MEMBER_KEY = None

_MembersIndex = dict[object, ITrackable]


class SQLAlchemyTrackableSet(
    _SQLAlchemyTrackableBase,
    MutableSet[T],
):
    """SQLAlchemy MutableSet integrated with the mutrack graph.

    Every trackable member is linked under the key ``None``.

    Members are never wrapped: set members must be hashable, and the
    plain containers that wrapping converts (``list``, ``dict``,
    ``set``) are not.

    Set lookups are by equality, so the object passed to ``remove`` may
    be a different (equal) object than the stored member. To unlink the
    stored member in O(1), trackable members are kept in an index
    mapping each member to itself. The index is built lazily from the
    current contents on the first mutation, because ``wrapping``
    populates fresh sets with raw ``set.add`` calls.

    Raw ``set`` methods are used internally to avoid the notification
    hooks implemented by SQLAlchemy's ``MutableSet``. Each public
    mutation emits exactly one ``changed()`` notification; operations
    that leave the set unchanged (e.g. adding an existing member) emit
    none.
    """

    def __init__(
        self,
        iterable: Iterable[T] = (),
        /,
    ) -> None:
        """Prepare stored set members and links without notifying.

        Args:
            iterable: Source values materialized before the operation.
        """
        replacement = set(iterable)
        members: _MembersIndex = {
            member: member
            for _, member in iter_trackable_items(list(replacement))
        }
        old_members = [
            member for _, member in iter_trackable_items(list(self))
        ]

        created = link_entries(
            self,
            ((_MEMBER_KEY, member) for member in members.values()),
        )

        try:
            set.__init__(self, replacement)
        except Exception:
            unlink_entries(self, created)
            raise

        retained_ids = {id(member) for member in members.values()}
        unlink_entries(
            self,
            (
                (_MEMBER_KEY, member)
                for member in old_members
                if id(member) not in retained_ids
            ),
        )
        raw_setattr(
            self,
            TRACKED_MEMBERS_STORE,
            members or None,
        )

    def _members_index(self) -> _MembersIndex:
        """Return the trackable-member index, building it if needed.

        Must be obtained *before* members are removed, so that removed
        members can still be found in it.

        Returns:
            Stored Trackable set representatives indexed by equality.
        """
        index: _MembersIndex | None = cast(
            "_MembersIndex | None",
            raw_getattr(
                self,
                TRACKED_MEMBERS_STORE,
                None,
            ),
        )

        if index is None:
            index = {
                member: member
                for _, member in iter_trackable_items(list(self))
            }

            raw_setattr(
                self,
                TRACKED_MEMBERS_STORE,
                index,
            )

        return index

    def _new_members(
        self,
        values: set[Any] | frozenset[Any],
        /,
    ) -> _MembersIndex:
        """New trackable representatives from already-deduplicated values.

        Args:
            values: Incoming values processed by the operation.

        Returns:
            New Trackable representatives that are absent from this
            set.
        """
        fresh: _MembersIndex = {}

        for _, member in iter_trackable_items(list(values)):
            if member not in self:
                fresh[member] = member

        return fresh

    def _forget(
        self,
        index: _MembersIndex,
        elem: object,
        /,
    ) -> None:
        """Unlink the stored member equal to the removed ``elem``.

        Set removal resolves the stored representative rather than
        unlinking an equal probe. Unhashable set probes fall back to
        scanning removed representatives.

        Args:
            index: Equality-keyed index of stored Trackable set members.
            elem: Equality probe used to locate a stored set member.
        """
        if not index:
            return

        try:
            stored = index.pop(
                elem,
                None,
            )

        except TypeError:
            self._forget_removed(index)
            return

        if stored is not None:
            self._state.unlink(
                stored,
                _MEMBER_KEY,
            )

    def _forget_removed(
        self,
        index: _MembersIndex,
        /,
    ) -> None:
        """Unlink indexed members that are no longer in the set.

        Args:
            index: Equality-keyed index of stored Trackable set members.
        """
        removed = [member for member in index.values() if member not in self]

        for member in removed:
            del index[member]

        unlink_entries(
            self,
            ((_MEMBER_KEY, member) for member in removed),
        )

    def _add_values(
        self,
        values: list[Any],
        /,
    ) -> None:
        """Stage stored representatives, preserving a valid partial prefix.

        If hashing fails, built-in set.update retains preceding values
        in the staging set. Commit that prefix before re-raising, just
        as a direct set.update would, without linking discarded equal
        objects.

        Args:
            values: Incoming values processed by the operation.
        """
        staged: set[Any] = set()

        try:
            set.update(staged, values)
        finally:
            self._add_members(staged)

    def _add_members(self, values: set[Any], /) -> None:
        """Link and add staged representatives without notifying.

        Args:
            values: Incoming values processed by the operation.
        """
        prepared = prepare_runtime_values(self, values)
        if prepared is not None:
            values = set(prepared)
        fresh = self._new_members(values)

        link_entries(
            self,
            ((_MEMBER_KEY, member) for member in fresh.values()),
        )

        try:
            set.update(
                self,
                values,
            )

        finally:
            if fresh:
                index = self._members_index()

                for member in fresh.values():
                    if member in self:
                        index[member] = member
                    else:
                        self._state.unlink(
                            member,
                            _MEMBER_KEY,
                        )

    def add(
        self,
        elem: T,
    ) -> None:
        """Add a new set member and link it before emitting a notification.

        A failed index or storage write undoes newly created bookkeeping.
        Index restoration excludes the failed member by identity, without
        invoking its hash again.

        Args:
            elem: Hashable value to add if no equal member is stored.
        """
        if elem in self:
            return

        prepared = prepare_runtime_values(self, (elem,))
        if prepared is not None:
            elem = cast(T, prepared[0])
        if is_trackable(elem):
            index = self._members_index()

            created = self._state.link(
                elem,
                _MEMBER_KEY,
            )
            indexed = False
            try:
                index[elem] = elem
                indexed = True
                set.add(self, cast(T, elem))
            except BaseException as error:
                if indexed:
                    try:
                        restored = {
                            key: member
                            for key, member in index.items()
                            if member is not elem
                        }
                        raw_setattr(self, TRACKED_MEMBERS_STORE, restored)
                    except BaseException as failure:
                        error.add_note(
                            f"Set member index rollback failed: {failure!r}"
                        )
                if created:
                    try:
                        self._state.unlink(elem, _MEMBER_KEY)
                    except BaseException as failure:
                        error.add_note(
                            f"Set link rollback failed: {failure!r}"
                        )
                raise
        else:
            set.add(self, elem)

        self.changed()

    def remove(
        self,
        elem: object,
    ) -> None:
        """Remove a matching value and unlink the stored representative.

        Args:
            elem: Equality probe used to locate a stored set member.
        """
        index = self._members_index()

        set.remove(
            cast("set[object]", self),
            elem,
        )

        self._forget(
            index,
            elem,
        )

        self.changed()

    def discard(
        self,
        elem: object,
    ) -> None:
        """Discard a member and unlink its stored representative.

        Args:
            elem: Equality probe used to locate a stored set member.
        """
        if elem not in self:
            return

        self.remove(elem)

    def pop(
        self,
        *arg: Any,
    ) -> T:
        """Pop a set member and unlink its stored representative.

        Args:
            *arg: Positional arguments forwarded to the built-in
                collection operation.

        Returns:
            An arbitrary stored set member.
        """
        index = self._members_index()

        elem: T = set.pop(self, *arg)

        self._forget(
            index,
            elem,
        )

        self.changed()

        return elem

    def clear(self) -> None:
        """Clear contents and links, notifying on change."""
        if not self:
            return

        self._clear_members()

        self.changed()

    def _clear_members(self) -> None:
        """Clear storage and child links without notifying."""
        index = self._members_index()
        members = list(index.values())

        set.clear(self)
        index.clear()

        unlink_entries(
            self,
            ((_MEMBER_KEY, member) for member in members),
        )

    def update(
        self,
        *arg: Iterable[T],
    ) -> None:
        """Add values and link their stored representatives.

        Args:
            *arg: Positional arguments forwarded to the built-in
                collection operation.
        """
        values = list(chain.from_iterable(arg))

        if not values:
            return

        size = len(self)

        try:
            self._add_values(values)

        finally:
            if len(self) != size:
                self.changed()

    def intersection_update(
        self,
        *arg: Iterable[Any],
    ) -> None:
        """Keep common members without replacing their stored identities.

        Args:
            *arg: Positional arguments forwarded to the built-in
                collection operation.
        """
        common = set.intersection(
            self,
            *arg,
        )

        if len(common) == len(self):
            return

        removed = set.difference(
            self,
            common,
        )

        index = self._members_index()

        set.difference_update(
            self,
            removed,
        )

        for member in removed:
            if is_trackable(member):
                index.pop(member, None)

                self._state.unlink(
                    member,
                    _MEMBER_KEY,
                )

        self.changed()

    def difference_update(
        self,
        *arg: Iterable[Any],
    ) -> None:
        """Remove matches and reconcile links on iteration failure.

        Args:
            *arg: Positional arguments forwarded to the built-in
                collection operation.
        """
        index = self._members_index()
        size = len(self)

        try:
            set.difference_update(
                self,
                *arg,
            )
        finally:
            if len(self) != size:
                self._forget_removed(index)
                self.changed()

    def symmetric_difference_update(
        self,
        *arg: Iterable[T],
    ) -> None:
        """Toggle membership against one iterable and reconcile child links.

        Args:
            *arg: Positional arguments forwarded to the built-in
                collection operation.

        Raises:
            TypeError: An argument or object does not meet the required
                protocol.
        """
        if len(arg) != 1:
            raise TypeError(
                "symmetric_difference_update() takes exactly one argument "
                f"({len(arg)} given)"
            )

        other = arg[0] if isinstance(arg[0], (set, frozenset)) else set(arg[0])
        prepared = prepare_runtime_values(self, other)
        if prepared is not None:
            other = set(prepared)

        if not other:
            return

        index = self._members_index()

        fresh = self._new_members(other)

        link_entries(
            self,
            ((_MEMBER_KEY, member) for member in fresh.values()),
        )

        set.symmetric_difference_update(
            self,
            other,
        )

        self._forget_removed(index)
        index.update(fresh)

        self.changed()
