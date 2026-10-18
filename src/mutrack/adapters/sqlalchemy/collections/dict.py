"""Track nested mutations in SQLAlchemy dict containers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypeVar, cast, overload

from sqlalchemy.ext.mutable import MutableDict

from mutrack.adapters.sqlalchemy.collections.base import (
    _SQLAlchemyTrackableCollection,
)
from mutrack.internal.sentinel import MISSING
from mutrack.tracking.graph.linking.collections import (
    LinkEntry,
    iter_trackable_items,
    link_entries,
    unlink_entries,
)
from mutrack.tracking.trackable.protocols import is_trackable
from mutrack.tracking.types import Key

KT = TypeVar("KT")
VT = TypeVar("VT")
NewKT = TypeVar("NewKT")
NewVT = TypeVar("NewVT")


class SQLAlchemyTrackableDict(
    _SQLAlchemyTrackableCollection,
    MutableDict[KT, VT],
):
    """SQLAlchemy MutableDict integrated with the mutrack graph.

    Every direct trackable value is linked under its dict key. Keys are
    never wrapped; only values participate in tracking.

    New values are prepared (plain containers wrapped) and linked
    before the dict is physically changed; links of replaced or removed
    values are dropped afterwards. Values never shift between keys, so
    no snapshot reconciliation is needed.

    Raw ``dict`` methods are used internally to avoid the notification
    hooks implemented by SQLAlchemy's ``MutableDict``. Each public
    mutation emits exactly one ``changed()`` notification; operations
    that provably leave the dict unchanged (e.g. ``setdefault`` of an
    existing key, ``update()`` with no items) emit none.
    """

    def __init__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Prepare initial dictionary entries without notifying.

        Args:
            *args: Positional constructor arguments accepted by the
                underlying collection.
            **kwargs: Keyword constructor values accepted by the
                underlying collection.
        """
        if args or kwargs:
            self._merge(dict(*args, **kwargs))

    @overload
    @classmethod
    def fromkeys(
        cls,
        iterable: Iterable[NewKT],
        value: None = None,
        /,
    ) -> SQLAlchemyTrackableDict[NewKT, Any | None]: ...

    @overload
    @classmethod
    def fromkeys(
        cls,
        iterable: Iterable[NewKT],
        value: NewVT,
        /,
    ) -> SQLAlchemyTrackableDict[NewKT, NewVT]: ...

    @classmethod
    def fromkeys(
        cls,
        iterable: Iterable[Any],
        value: Any = None,
        /,
    ) -> SQLAlchemyTrackableDict[Any, Any]:
        """Build a dictionary with a shared prepared default.

        Args:
            iterable: Keys used to construct the new dictionary.
            value: Incoming value prepared before storage.

        Returns:
            A tracked dictionary sharing one prepared value across all
            keys.
        """
        return cls(
            dict.fromkeys(
                iterable,
                value,
            )
        )

    def _merge(
        self,
        incoming: dict[Any, Any],
        /,
        *,
        notify: bool = False,
    ) -> None:
        """Prepare entries and retain consistent links for committed writes.

        All incoming edges are checked before storage changes. If storage
        fails, successful prefix writes remain and unwritten edges roll back.
        Cleanup identifies unwritten keys without hashing them again.

        Args:
            incoming: Dictionary entries to merge into the tracked mapping.
            notify: Whether to notify for successful writes, even on failure.
        """
        keys = list(incoming)

        new_values = self._prepare_values(incoming.values())

        old_values = [dict.get(self, key, MISSING) for key in keys]

        fresh: list[LinkEntry] = [
            (keys[index], child)
            for index, child in iter_trackable_items(new_values)
            if child is not old_values[index]
        ]

        created = link_entries(
            self,
            fresh,
        )
        committed = 0
        try:
            for key, new, old in zip(keys, new_values, old_values):
                dict.__setitem__(self, key, new)
                committed += 1
                if old is not new:
                    self._forget(key, old)
        except BaseException as error:
            unwritten = {id(key) for key in keys[committed:]}
            self._rollback_entries(
                [entry for entry in created if id(entry[0]) in unwritten],
                error,
            )
            raise
        finally:
            if notify and committed:
                self.changed()

    def _rollback_entries(
        self, entries: list[LinkEntry], error: BaseException, /
    ) -> None:
        """Undo new edges in reverse order without masking a storage error.

        Args:
            entries: Newly created edges whose writes did not commit.
            error: Original failure receiving any cleanup exception notes.
        """
        for key, child in reversed(entries):
            try:
                self._state.unlink(child, key)
            except BaseException as failure:
                error.add_note(f"Dictionary link rollback failed: {failure!r}")

    def _store(
        self,
        key: Any,
        value: Any,
        old: object,
        /,
    ) -> object:
        """Store ``value`` under ``key`` replacing ``old`` (or MISSING).

        Returns the prepared value. Does not notify.

        Args:
            key: Dictionary key identifying the stored value.
            value: Incoming value prepared before storage.
            old: Previously stored value whose graph edge may need
                removal.

        Returns:
            The prepared value stored under the supplied key.
        """
        new = self._prepare_value(value)

        if new is old:
            return new

        created = link_entries(self, [(key, new)] if is_trackable(new) else [])
        try:
            dict.__setitem__(self, key, new)
        except BaseException as error:
            self._rollback_entries(created, error)
            raise

        if is_trackable(old):
            self._state.unlink(
                old,
                key,
            )

        return new

    def _forget(
        self,
        key: Any,
        old: object,
        /,
    ) -> None:
        """Unlink the previous child reference using its stored identity.

        Only Trackable old values have a parent edge to remove.

        Args:
            key: Dictionary key identifying the stored value.
            old: Previously stored value whose graph edge may need
                removal.
        """
        if is_trackable(old):
            self._state.unlink(
                old,
                cast(Key, key),
            )

    def __setitem__(
        self,
        key: KT,
        value: VT,
    ) -> None:
        """Store replacement values while keeping child links consistent.

        Args:
            key: Dictionary key identifying the stored value.
            value: Incoming value prepared before storage.
        """
        self._store(
            key,
            value,
            dict.get(self, key, MISSING),
        )

        self.changed()

    def setdefault(
        self,
        key: KT,
        value: Any = None,
    ) -> Any:
        """Return an existing value or prepare, link, and store the default.

        Args:
            key: Dictionary key identifying the stored value.
            value: Default prepared and stored only when the key is absent.

        Returns:
            The existing value or the newly prepared default.
        """
        existing = dict.get(
            self,
            key,
            MISSING,
        )

        if existing is not MISSING:
            return existing

        result = self._store(
            key,
            value,
            MISSING,
        )

        self.changed()

        return result

    def update(
        self,
        *a: Any,
        **kw: VT,
    ) -> None:
        """Merge prepared entries and emit one notification.

        Args:
            *a: Positional arguments accepted by dict.update.
            **kw: Keyword arguments forwarded to the built-in
                collection operation.
        """
        incoming = dict(*a, **kw)

        if not incoming:
            return

        self._merge(incoming, notify=True)

    def __delitem__(
        self,
        key: KT,
    ) -> None:
        """Delete stored values and remove or reconcile their child links.

        Args:
            key: Dictionary key identifying the stored value.
        """
        old = dict.pop(
            self,
            key,
        )

        self._forget(
            key,
            old,
        )

        self.changed()

    def pop(
        self,
        key: KT,
        *default: Any,
    ) -> Any:
        """Pop a stored value and repair its parent links.

        Args:
            key: Dictionary key identifying the stored value.
            *default: Fallback used when the requested value is absent.

        Returns:
            The removed value, or the dictionary fallback when
            supplied.

        Raises:
            TypeError: An argument or object does not meet the required
                protocol.
            KeyError: The requested key or set member is absent.
        """
        if len(default) > 1:
            raise TypeError(
                f"pop expected at most 2 arguments, got {len(default) + 1}"
            )

        old = dict.pop(
            self,
            key,
            MISSING,
        )

        if old is MISSING:
            if default:
                return default[0]

            raise KeyError(key)

        self._forget(
            key,
            old,
        )

        self.changed()

        return old

    def popitem(self) -> tuple[KT, VT]:
        """Remove and return the last dictionary entry and unlink its value.

        Returns:
            The removed dictionary key and its stored value.
        """
        key, old = dict.popitem(self)

        self._forget(
            key,
            old,
        )

        self.changed()

        return key, old

    def clear(self) -> None:
        """Clear contents and links, notifying on change."""
        if not self:
            return

        keys = list(self)

        entries: list[LinkEntry] = [
            (keys[index], child)
            for index, child in iter_trackable_items(list(self.values()))
        ]

        dict.clear(self)

        unlink_entries(
            self,
            entries,
        )

        self.changed()
