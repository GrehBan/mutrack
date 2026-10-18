"""Regression tests for sqlalchemy."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import JSON, PickleType, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from mutrack.adapters.sqlalchemy.collections.dict import (
    SQLAlchemyTrackableDict,
)
from mutrack.adapters.sqlalchemy.collections.list import (
    SQLAlchemyTrackableList,
)
from mutrack.adapters.sqlalchemy.collections.set import SQLAlchemyTrackableSet
from tests.helpers import (
    FailingHash,
    InputFailure,
    LegacySequence,
    PlainValue,
    TrackedValue,
    failing_input,
)


class Base(DeclarativeBase):
    """Declare base storage for this regression test."""

    pass


class SetRow(Base):
    """Persist a tracked set through an ORM mutable PickleType column."""

    __tablename__ = "set_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[set[Any]] = mapped_column(
        SQLAlchemyTrackableSet.as_mutable(PickleType)
    )


class ListRow(Base):
    """Persist a tracked list through an ORM mutable JSON column."""

    __tablename__ = "list_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[list[Any]] = mapped_column(
        SQLAlchemyTrackableList.as_mutable(JSON)
    )


class DictRow(Base):
    """Persist arbitrary tracked dictionary entries through PickleType."""

    __tablename__ = "dict_rows"

    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict[Any, Any]] = mapped_column(
        SQLAlchemyTrackableDict.as_mutable(PickleType)
    )


@pytest.fixture
def session() -> Iterator[Session]:
    """Provide an in-memory session for persistence tests.

    Yields:
        An isolated SQLAlchemy session with commit expiration disabled.
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as connection:
            yield connection
    finally:
        engine.dispose()


@pytest.mark.parametrize("failure_call", [2, 3])
def test_failed_set_add_does_not_dirty_owner(
    session: Session, failure_call: int
) -> None:
    """Keep rejected members from dirtying the mapped set's owner.

    Args:
        session: Isolated ORM session used for persistence checks.
        failure_call: Hash call failing in bookkeeping or physical storage.
    """
    survivor = TrackedValue(1)
    values = SQLAlchemyTrackableSet([survivor])
    row = SetRow(payload=values)
    session.add(row)
    session.commit()
    rejected = FailingHash(2)
    rejected.arm(failure_call)

    with pytest.raises(InputFailure, match="hash failed"):
        values.add(rejected)

    rejected.changed()
    assert row not in session.dirty
    assert not rejected._tracking_parents
    session.expire(row)
    assert row.payload == {TrackedValue(1)}
    stored = next(iter(row.payload))
    stored.changed()
    assert row in session.dirty


@pytest.mark.parametrize("operation", ["setitem", "setdefault"])
def test_failed_dictionary_write_does_not_dirty_owner(
    session: Session, operation: str
) -> None:
    """Prevent a rejected dictionary child from marking its ORM row dirty.

    Args:
        session: Isolated ORM session used for persistence checks.
        operation: Direct assignment or default insertion entry point.
    """
    values: SQLAlchemyTrackableDict[Any, Any] = SQLAlchemyTrackableDict()
    row = DictRow(payload=values)
    session.add(row)
    session.commit()
    key, child = FailingHash(10), TrackedValue(1)
    key.arm(3)

    with pytest.raises(InputFailure, match="hash failed"):
        if operation == "setitem":
            values[key] = child
        else:
            values.setdefault(key, child)

    child.changed()
    assert row not in session.dirty
    assert not child._tracking_parents
    session.expire(row)
    assert row.payload == {}


def test_partial_dictionary_update_is_persisted(session: Session) -> None:
    """Persist successful prefix writes after a later storage hash failure.

    Args:
        session: Isolated ORM session used for dirty tracking and reloading.
    """
    old, kept = TrackedValue(1), TrackedValue(2)
    rejected, unwritten = TrackedValue(3), TrackedValue(4)
    values: SQLAlchemyTrackableDict[Any, Any] = SQLAlchemyTrackableDict(
        {"first": old}
    )
    row = DictRow(payload=values)
    session.add(row)
    session.commit()
    key = FailingHash(10)
    incoming = {"first": kept, key: rejected, "last": unwritten}
    key.arm(3)

    with pytest.raises(InputFailure, match="hash failed"):
        values.update(incoming)

    assert row in session.dirty
    assert values == {"first": kept}
    session.commit()
    old.changed()
    rejected.changed()
    unwritten.changed()
    assert row not in session.dirty
    session.expire(row)
    assert row.payload == {"first": TrackedValue(2)}
    row.payload["first"].changed()
    assert row in session.dirty


def test_partial_difference_failure_is_persisted(session: Session) -> None:
    """Verify partial difference failure is persisted.

    Args:
        session: Isolated ORM session used to check dirty tracking and
            persistence.
    """
    values = SQLAlchemyTrackableSet([1, 2])
    row = SetRow(payload=values)
    session.add(row)
    session.commit()

    with pytest.raises(InputFailure):
        values.difference_update(failing_input(1))

    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload == {2}


def test_partial_trackable_removal_unlinks_and_persists(
    session: Session,
) -> None:
    """Verify partial trackable removal unlinks and persists.

    Args:
        session: Isolated ORM session used to check dirty tracking and
            persistence.
    """
    child = TrackedValue(1)
    values = SQLAlchemyTrackableSet([child, TrackedValue(2)])
    row = SetRow(payload=values)
    session.add(row)
    session.commit()

    with pytest.raises(InputFailure):
        values.difference_update(failing_input(child))

    assert not child._tracking_parents
    assert row in session.dirty
    session.commit()
    child.changed()
    assert row not in session.dirty
    session.expire_all()
    assert row.payload == {TrackedValue(2)}


def test_failed_difference_without_removal_keeps_orm_clean(
    session: Session,
) -> None:
    """Verify failed difference without removal keeps orm clean.

    Args:
        session: Isolated ORM session used to check dirty tracking and
            persistence.
    """
    values = SQLAlchemyTrackableSet([1, 2])
    row = SetRow(payload=values)
    session.add(row)
    session.commit()

    with pytest.raises(InputFailure):
        values.difference_update(failing_input(3))

    assert row not in session.dirty


@pytest.mark.parametrize("operation", ["construct", "update"])
def test_equal_nonmember_does_not_dirty_orm(
    session: Session, operation: str
) -> None:
    """Verify equal nonmember does not dirty orm.

    Args:
        session: Isolated ORM session used to check dirty tracking and
            persistence.
        operation: Mutation callback or wrapping entry point exercised
            by the call.
    """
    plain, tracked = PlainValue(), TrackedValue()
    values = SQLAlchemyTrackableSet([plain])
    if operation == "construct":
        values = SQLAlchemyTrackableSet([plain, tracked])
    row = SetRow(payload=values)
    session.add(row)
    session.commit()
    if operation == "update":
        values.update([tracked])

    tracked.changed()

    assert row not in session.dirty
    assert next(iter(values)) is plain
    session.expire_all()
    assert type(next(iter(row.payload))) is PlainValue


def test_cycle_rejection_keeps_orm_usable(session: Session) -> None:
    """Verify cycle rejection keeps orm usable.

    Args:
        session: Isolated ORM session used to check dirty tracking and
            persistence.
    """
    values = SQLAlchemyTrackableList([{"nested": []}])
    row = ListRow(payload=values)
    session.add(row)
    session.commit()

    with pytest.raises(ValueError, match="cyclic"):
        values[0]["nested"].append(values)

    assert row not in session.dirty
    values[0]["nested"].append(1)
    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload == [{"nested": [1]}]
    row.payload[0]["nested"].append(2)
    assert row in session.dirty


def test_legacy_sequence_slice_is_persisted(session: Session) -> None:
    """Verify legacy sequence slice is persisted.

    Args:
        session: Isolated ORM session used to check dirty tracking and
            persistence.
    """
    values: Any = SQLAlchemyTrackableList([1, 2])
    row = ListRow(payload=values)
    session.add(row)
    session.commit()

    values[:] = LegacySequence([3, {"nested": []}])

    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload == [3, {"nested": []}]


def test_sort_discards_callback_links_without_later_orm_notifications(
    session: Session,
) -> None:
    """Verify sort discards callback links without later orm notifications.

    Args:
        session: Isolated ORM session used to check dirty tracking and
            persistence.
    """
    values: Any = SQLAlchemyTrackableList([[2], [1]])
    original = values[0]
    discarded = TrackedValue()
    row = ListRow(payload=values)
    session.add(row)
    session.commit()

    def key(value: list[int]) -> int:
        """Run the callback mutation or failure and return the sorting key.

        Args:
            value: Value to read, prepare, store, or compare.

        Returns:
            The key used to order the current list value.
        """
        values.append(discarded)
        return value[0]

    with pytest.raises(ValueError):
        values.sort(key=key)

    assert row in session.dirty
    assert values._state not in discarded._tracking_parents
    session.commit()
    discarded.changed()
    assert row not in session.dirty
    original.append(3)
    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload == [[1], [2, 3]]


def test_depth_limit_rejection_keeps_orm_clean(session: Session) -> None:
    """Verify depth limit rejection keeps orm clean.

    Args:
        session: Isolated ORM session used to check dirty tracking and
            persistence.
    """

    class LimitedList(SQLAlchemyTrackableList[Any]):
        """Apply a small wrapping-depth limit for boundary validation."""

        _max_depth_limit = 4

    values = LimitedList([1])
    row = ListRow(payload=values)
    session.add(row)
    session.commit()
    child = TrackedValue()
    shared = [child, []]

    with pytest.raises(ValueError, match="max depth"):
        values.append([shared, [[shared]]])

    assert values == [1]
    assert not child._tracking_parents
    assert row not in session.dirty


@pytest.mark.parametrize("count", [10**100, -(10**100)])
def test_invalid_repetition_keeps_orm_contents_and_links(
    session: Session, count: int
) -> None:
    """Verify invalid repetition keeps orm contents and links.

    Args:
        session: Isolated ORM session used to check dirty tracking and
            persistence.
        count: Repetition count exercised by the test.
    """
    values: Any = SQLAlchemyTrackableList([[]])
    child = values[0]
    row = ListRow(payload=values)
    session.add(row)
    session.commit()

    with pytest.raises(OverflowError):
        values.__imul__(count)

    assert row not in session.dirty
    assert len(values) == 1 and values[0] is child
    assert child._tracking_parents[values._state] == {0}
    child.append(1)
    assert row in session.dirty


def test_repeated_alias_mutations_are_persisted(session: Session) -> None:
    """Verify repeated alias mutations are persisted.

    Args:
        session: Isolated ORM session used to check dirty tracking and
            persistence.
    """
    values = SQLAlchemyTrackableList([[]])
    row = ListRow(payload=values)
    session.add(row)
    session.commit()

    values.__imul__(3)
    assert values[0] is values[1] is values[2]
    session.commit()
    values[0].append(1)
    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload == [[1], [1], [1]]
