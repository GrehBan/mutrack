"""Persist adapter models and track field and nested-container mutations."""

from __future__ import annotations

from collections.abc import Iterator
from copy import copy
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from gc import collect
from typing import Any
from uuid import UUID
from weakref import ref

import attrs
import pytest
from pydantic import BaseModel
from pydantic.v1 import BaseModel as V1BaseModel
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from mutrack.adapters.attrs.fields import ATTRS_FIELDS
from mutrack.adapters.dataclasses.fields import DATACLASS_FIELDS
from mutrack.adapters.plain.fields import PLAIN_FIELDS
from mutrack.adapters.pydantic.fields import PYDANTIC_FIELDS
from mutrack.adapters.sqlalchemy.columns import TrackedJSON
from mutrack.tracking.field_access import CompositeFieldAccess, FieldAccess
from mutrack.tracking.serialization import decode_json
from mutrack.tracking.trackable.protocols import is_trackable
from mutrack.tracking.trackable.trackable import Trackable


@dataclass(eq=False)
class DataChild(Trackable):
    """Store a dataclass child whose list needs recursive preparation."""

    tags: list[str] = field(default_factory=list)


@dataclass(eq=False)
class DataDocument(Trackable):
    """Store a dataclass document with scalar, model, and container fields."""

    title: str
    child: DataChild
    children: list[DataChild]
    metadata: dict[str, list[int]]
    flags: set[str]


@attrs.define(eq=False)
class AttrsChild(Trackable):
    """Store an attrs child with slot-backed mutable fields."""

    tags: list[str] = attrs.field(factory=list)


@attrs.define(eq=False)
class AttrsDocument(Trackable):
    """Store an attrs document with native generated assignment methods."""

    title: str
    child: AttrsChild
    children: list[AttrsChild]
    metadata: dict[str, list[int]]
    flags: set[str]


class PlainChild(Trackable):
    """Store a plain child with annotated mutable fields."""

    tags: list[str]

    def __init__(self, tags: list[str]) -> None:
        """Initialize unprepared plain fields.

        Args:
            tags: Initial tag values.
        """
        self.tags = tags


class PlainDocument(Trackable):
    """Store plain model fields using an ordinary keyword constructor."""

    title: str
    child: PlainChild
    children: list[PlainChild]
    metadata: dict[str, list[int]]
    flags: set[str]

    def __init__(
        self,
        title: str,
        child: PlainChild,
        children: list[PlainChild],
        metadata: dict[str, list[int]],
        flags: set[str],
    ) -> None:
        """Store initial fields without mutation tracking configuration.

        Args:
            title: Initial scalar value.
            child: Direct nested child.
            children: Nested children reached through a list.
            metadata: Nested mutable dictionary values.
            flags: Hashable set members.
        """
        self.title = title
        self.child = child
        self.children = children
        self.metadata = metadata
        self.flags = flags


class PydanticChild(Trackable, BaseModel):
    """Validate nested fields through the installed Pydantic API."""

    tags: list[str]


class PydanticDocument(Trackable, BaseModel):
    """Store a Pydantic document without inheriting SQLAlchemy Mutable."""

    title: str
    child: PydanticChild
    children: list[PydanticChild]
    metadata: dict[str, list[int]]
    flags: set[str]


class V1Child(Trackable, V1BaseModel):
    """Validate nested fields using the Pydantic v1 namespace."""

    tags: list[str]


class V1Document(Trackable, V1BaseModel):
    """Store a document using Pydantic v1 validation and storage."""

    title: str
    child: V1Child
    children: list[V1Child]
    metadata: dict[str, list[int]]
    flags: set[str]


CASES = [
    (DataDocument, DATACLASS_FIELDS),
    (AttrsDocument, ATTRS_FIELDS),
    (PlainDocument, PLAIN_FIELDS),
    (PydanticDocument, PYDANTIC_FIELDS),
    (V1Document, PYDANTIC_FIELDS),
]


def document_data() -> dict[str, Any]:
    """Return fresh JSON-compatible document input for every test.

    Returns:
        A document containing all supported mutable field shapes.
    """
    return {
        "title": "initial",
        "child": {"tags": []},
        "children": [{"tags": []}],
        "metadata": {"counts": []},
        "flags": ["first"],
    }


@pytest.fixture(params=CASES, ids=lambda case: case[0].__name__)
def mapped(
    request: pytest.FixtureRequest,
) -> Iterator[tuple[Session, type[Any], type[Any], FieldAccess]]:
    """Map a fresh document column for each model framework.

    Args:
        request: Parameterized model class and field adapter.

    Yields:
        Isolated session, mapped row class, model type, and field adapter.
    """
    model_type, fields = request.param

    class Base(DeclarativeBase):
        """Declare isolated mappings for a single document-column test."""

        pass

    class Row(Base):
        """Map a nullable document using the selected framework adapter."""

        __tablename__ = "documents"
        id: Mapped[int] = mapped_column(primary_key=True)
        payload: Mapped[Any] = mapped_column(
            TrackedJSON(model_type, fields=fields), nullable=True
        )

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            yield session, Row, model_type, fields
    finally:
        engine.dispose()
        Base.registry.dispose()


def test_mapping_assignment_and_every_mutation_survive_reload(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Track scalar and nested mutations immediately and after database loads.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, model_type, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    assert isinstance(row.payload, model_type)

    row.payload.title = "changed"
    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload.title == "changed"

    row.payload.child.tags.append("direct")
    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload.child.tags == ["direct"]

    row.payload.children[0].tags.append("listed")
    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload.children[0].tags == ["listed"]

    row.payload.metadata["counts"].append(1)
    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload.metadata == {"counts": [1]}

    row.payload.flags.add("second")
    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload.flags == {"first", "second"}
    assert row not in session.dirty


def test_typed_assignment_prepares_without_copying(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Prepare an already constructed instance before attaching ORM ownership.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, model_type, fields = mapped
    model = decode_json(document_data(), model_type, fields)
    row = row_type(payload=model)
    assert row.payload is model
    session.add(row)
    session.commit()
    model.child.tags.append("typed")
    assert row in session.dirty


def test_field_replacement_unlinks_old_children_and_wraps_new_values(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Maintain replacement links and detect later mutations of new fields.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    old = row.payload.child.tags
    row.payload.child.tags = ["replacement"]
    assert row in session.dirty
    session.commit()
    old.append("detached")
    assert row not in session.dirty
    row.payload.child.tags.append("live")
    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload.child.tags == ["replacement", "live"]


def test_new_models_inside_containers_are_prepared_automatically(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Build and instrument a model introduced by a container mutation.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    child_type = type(row.payload.child)
    child = child_type(tags=[])
    row.payload.children.append(child)
    session.commit()
    row.payload.children[-1].tags.append("new")
    assert row in session.dirty
    session.commit()
    session.expire_all()
    assert row.payload.children[-1].tags == ["new"]


def test_replacing_or_expiring_column_detaches_previous_root(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Ignore mutations from old roots after replacement and expiration.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    old = row.payload
    setattr(row, "payload", document_data())
    session.commit()
    old.child.tags.append("old")
    assert row not in session.dirty
    stale = row.payload
    session.expire(row, ["payload"])
    stale.child.tags.append("expired")
    assert row not in session.dirty
    assert row.payload.child.tags == []
    row.payload = None
    session.commit()
    session.expire_all()
    assert row.payload is None


def test_json_queries_keep_native_index_semantics(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Allow JSON path expressions while reconstructing selected documents.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    session.add(row_type(payload=document_data()))
    session.commit()
    statement = select(row_type).where(
        row_type.payload["title"].as_string() == "initial"
    )
    assert session.scalars(statement).one().payload.title == "initial"
    assert session.scalar(select(row_type.payload["title"])) == "initial"
    assert session.scalar(select(row_type.payload["child"])) == {"tags": []}


def test_failed_model_cycle_restores_field_and_keeps_owner_clean(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Restore the previous field identity when a model assignment forms a cycle.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    child = row.payload.child
    previous = child.tags
    with pytest.raises(ValueError, match="cyclic"):
        child.tags = child
    assert child.tags is previous
    assert row not in session.dirty
    child.tags.append("after failure")
    assert row in session.dirty


def test_nested_model_replacement_unlinks_the_previous_model(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Attach newly assigned model fields and remove the old model's parent edge.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    old = row.payload.child
    replacement = type(old)(tags=[])
    row.payload.child = replacement
    session.commit()
    old.tags.append("removed")
    assert row not in session.dirty
    row.payload.child.tags.append("replacement")
    assert row in session.dirty


def test_shared_model_marks_both_owners_dirty_and_detaches_independently(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Propagate to every owner without retaining or disconnecting other rows.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    first = row_type(payload=document_data())
    second = row_type(payload=first.payload)
    session.add_all([first, second])
    session.commit()
    first.payload.child.tags.append("shared")
    assert first in session.dirty and second in session.dirty
    session.commit()
    shared = second.payload
    first.payload = None
    session.commit()
    shared.title = "still shared"
    assert first not in session.dirty and second in session.dirty


def test_observers_do_not_keep_orm_owners_alive(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Allow ORM rows to be collected while an external reference keeps the model.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    model = row.payload
    weak_row = ref(row)
    session.expunge(row)
    del row
    collect()
    assert weak_row() is None
    model.child.tags.append("owner collected")


def test_refresh_and_merge_restore_live_ownership(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Reconnect mutation propagation after refresh and merge without loading.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    session.refresh(row, ["payload"])
    row.payload.child.tags.append("refreshed")
    assert row in session.dirty
    session.commit()
    session.expunge(row)
    merged = session.merge(row, load=False)
    merged.payload.title = "merged"
    assert merged in session.dirty
    session.commit()
    session.expire_all()
    assert merged.payload.title == "merged"


@dataclass(eq=False)
class MixedDocument(Trackable):
    """Contain nested models from every supported framework."""

    data: DataChild
    attrs: AttrsChild
    plain: PlainChild
    pydantic: PydanticChild


def test_mixed_adapters_support_nested_models_and_initial_silence() -> None:
    """Decode a mixed graph and detect mutations from each nested framework."""
    fields = CompositeFieldAccess(
        PYDANTIC_FIELDS, DATACLASS_FIELDS, ATTRS_FIELDS, PLAIN_FIELDS
    )
    column = TrackedJSON(MixedDocument, fields=fields)
    model = column.prepare(
        {name: {"tags": []} for name in ("data", "attrs", "plain", "pydantic")}
    )
    assert model is not None
    assert column.python_type is MixedDocument
    for name in ("data", "attrs", "plain", "pydantic"):
        child = getattr(model, name)
        assert child._tracking_parents[model._state] == {name}
        child.tags = ["new"]
        assert is_trackable(child.tags)
        assert child.tags._tracking_parents[child._state] == {"tags"}


class Status(Enum):
    """Define a typed enum preserved across JSON serialization."""

    OPEN = "open"


@dataclass(eq=False)
class TypedDocument(Trackable):
    """Exercise annotated scalar reconstruction and non-init mutable fields."""

    day: date
    amount: Decimal
    identifier: UUID
    status: Status
    history: list[str] = field(default_factory=list, init=False)


def test_serialization_round_trips_typed_scalars_and_non_init_fields() -> None:
    """Serialize declared fields without tracking metadata and reconstruct types."""
    from mutrack.tracking.serialization import encode_json

    column = TrackedJSON(TypedDocument, fields=DATACLASS_FIELDS)
    model = TypedDocument(
        date(2026, 1, 2), Decimal("1.25"), UUID(int=1), Status.OPEN
    )
    model.history.append("persisted")
    prepared = column.prepare(model)
    encoded = encode_json(prepared, DATACLASS_FIELDS)
    assert encoded == {
        "day": "2026-01-02",
        "amount": "1.25",
        "identifier": str(UUID(int=1)),
        "status": "open",
        "history": ["persisted"],
    }
    restored = column.prepare(encoded)
    assert restored is not None
    assert restored.day == model.day
    assert restored.amount == model.amount
    assert restored.identifier == model.identifier
    assert restored.status is Status.OPEN
    assert restored.history == ["persisted"]


@attrs.define(eq=False)
class ConvertedDocument(Trackable):
    """Validate and convert field assignments through attrs native setters."""

    count: int = attrs.field(converter=int, validator=attrs.validators.ge(0))
    _tags: list[str] = attrs.field(factory=list, alias="tags")
    history: list[str] = attrs.field(factory=list, init=False)


def test_attrs_converter_validation_aliases_and_non_init_fields() -> None:
    """Keep attrs conversion, validation, aliases, and persisted storage names."""
    from mutrack.tracking.serialization import encode_json

    column = TrackedJSON(ConvertedDocument, fields=ATTRS_FIELDS)
    model: Any = column.prepare({"count": "1", "tags": [], "history": ["old"]})
    model.count = "2"
    assert model.count == 2
    with pytest.raises(ValueError):
        model.count = -1
    assert model.count == 2
    model._tags.append("tag")
    restored: Any = column.prepare(encode_json(model, ATTRS_FIELDS))
    assert restored.count == 2
    assert restored._tags == ["tag"]
    assert restored.history == ["old"]


@dataclass(frozen=True)
class FrozenDocument(Trackable):
    """Keep frozen field restrictions while allowing nested list mutations."""

    tags: list[str]


def test_frozen_models_retain_native_field_assignment_restrictions() -> None:
    """Prepare frozen fields raw while rejecting later forbidden assignments."""
    from dataclasses import FrozenInstanceError

    model: Any = TrackedJSON(FrozenDocument, fields=DATACLASS_FIELDS).prepare(
        {"tags": []}
    )
    before = model.tags
    with pytest.raises(FrozenInstanceError):
        model.tags = ["forbidden"]
    assert model.tags is before
    model.tags.append("allowed")
    assert model.tags == ["allowed"]


def test_augmented_assignment_notifies_one_time(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Avoid a second field notification after in-place container mutation.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    modified: list[str] = []

    def observe(target: object, token: object) -> None:
        """Record modifications emitted for this mapped column.

        Args:
            target: ORM instance whose column changed.
            token: Attribute modification event token.
        """
        modified.append("payload")

    event.listen(row_type.payload, "modified", observe)
    row.payload.child.tags += ["augmented"]
    assert modified == ["payload"]


class ValidatedV1(Trackable, V1BaseModel):
    """Exercise assignment validation and fields-set rollback in Pydantic v1."""

    count: int = 1
    tags: list[str] = []

    class Config:
        """Enable native Pydantic assignment validation."""

        validate_assignment = True


def test_pydantic_validation_failure_keeps_fields_and_metadata() -> None:
    """Retain native validation and restore Pydantic metadata on graph failure."""
    model: Any = TrackedJSON(ValidatedV1, fields=PYDANTIC_FIELDS).prepare({})
    model.count = "2"
    assert model.count == 2
    fields_set = set(model.__fields_set__)
    with pytest.raises(ValueError):
        model.count = "invalid"
    assert model.count == 2
    assert model.__fields_set__ == fields_set
    before = model.tags
    with pytest.raises(ValueError):
        model.tags = [model.tags]
    assert model.tags is before
    assert model.__fields_set__ == fields_set


def test_pydantic_v2_native_validators_and_fields_set() -> None:
    """Preserve native v2 assignment validation before graph maintenance."""
    import pydantic

    if not hasattr(BaseModel, "model_validate"):
        pytest.skip("Pydantic v2-specific assignment configuration.")
    model_type: Any = pydantic.create_model(
        "ValidatedV2",
        __base__=PydanticChild,
        __config__=pydantic.ConfigDict(validate_assignment=True),
    )
    model: Any = TrackedJSON(model_type, fields=PYDANTIC_FIELDS).prepare(
        {"tags": []}
    )
    before = model.tags
    fields_set = set(model.model_fields_set)
    with pytest.raises(ValueError):
        model.tags = [object()]
    assert model.tags is before
    assert model.model_fields_set == fields_set


def test_inherited_columns_and_multiple_document_attributes() -> None:
    """Track inherited and sibling columns without duplicate ownership hooks."""

    class Base(DeclarativeBase):
        """Declare test mappings for inherited document columns."""

        pass

    class Parent(Base):
        """Declare a document column on a polymorphic ORM base."""

        __tablename__ = "inherited"
        id: Mapped[int] = mapped_column(primary_key=True)
        kind: Mapped[str] = mapped_column()
        payload: Mapped[Any] = mapped_column(
            TrackedJSON(DataChild, fields=DATACLASS_FIELDS)
        )
        other: Mapped[Any] = mapped_column(
            TrackedJSON(PlainChild, fields=PLAIN_FIELDS)
        )
        __mapper_args__ = {
            "polymorphic_on": kind,
            "polymorphic_identity": "parent",
        }

    class Child(Parent):
        """Inherit the base document mapping through single-table inheritance."""

        __mapper_args__ = {"polymorphic_identity": "child"}

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            row = Child(payload={"tags": []}, other={"tags": []})
            session.add(row)
            session.commit()
            row.payload.tags.append("inherited")
            assert row in session.dirty
            session.commit()
            row.other.tags = ["sibling"]
            assert row in session.dirty
            session.commit()
            session.expire_all()
            assert row.payload.tags == ["inherited"]
            assert row.other.tags == ["sibling"]
    finally:
        engine.dispose()
        Base.registry.dispose()


def test_shallow_copies_receive_their_own_root_identity(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Separate copied root ownership while preserving intentionally shared children.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    first = row_type(payload=document_data())
    session.add(first)
    session.commit()
    second = row_type(payload=copy(first.payload))
    session.add(second)
    session.commit()
    assert first.payload._state is not second.payload._state
    second.payload.title = "copy only"
    assert first not in session.dirty and second in session.dirty
    session.commit()
    first.payload.child.tags.append("shared child")
    assert first in session.dirty and second in session.dirty


def test_batching_coalesces_configured_field_and_container_changes(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Use ordinary batching for multiple mutations of a tracked document.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    from mutrack.tracking.suppression import batch_changes

    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    with batch_changes(row.payload):
        row.payload.title = "batched"
        row.payload.child.tags.append("batched")
        assert row not in session.dirty
    assert row in session.dirty


def test_failed_column_assignment_preserves_existing_live_owner(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Keep previous ownership when document decoding rejects a replacement.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    previous = row.payload
    with pytest.raises((TypeError, ValueError)):
        row.payload = 42
    assert row.payload is previous
    assert row not in session.dirty
    previous.child.tags.append("still owned")
    assert row in session.dirty


def test_cyclic_and_deep_mapping_inputs_fail_before_recursive_decoding() -> (
    None
):
    """Reject malformed JSON-like input without exhausting Python recursion."""
    column = TrackedJSON(PlainChild, fields=PLAIN_FIELDS, max_depth=4)
    cyclic: dict[str, Any] = {}
    cyclic["tags"] = cyclic
    with pytest.raises(ValueError, match="cyclic"):
        column.prepare(cyclic)
    deep: Any = []
    for _ in range(1000):
        deep = [deep]
    with pytest.raises(ValueError, match="depth"):
        column.prepare({"tags": deep})


def test_custom_serialization_and_postgresql_storage_are_explicit() -> None:
    """Use caller codecs and compile a JSONB column without requiring a server."""
    from sqlalchemy import Column, MetaData, Table
    from sqlalchemy.dialects.postgresql import JSONB, dialect
    from sqlalchemy.schema import CreateTable

    def encode(model: PlainChild) -> object:
        """Encode a document using a custom wire field name.

        Args:
            model: Model being persisted.

        Returns:
            Application-specific JSON object data.
        """
        return {"labels": list(model.tags)}

    def decode(value: Any) -> PlainChild:
        """Reconstruct a model from the custom wire format.

        Args:
            value: Application-specific JSON object data.

        Returns:
            An unprepared model to be initialized by the column type.
        """
        return PlainChild(value["labels"])

    column = TrackedJSON(
        PlainChild,
        fields=PLAIN_FIELDS,
        encode=encode,
        decode=decode,
        storage=JSONB(),
    )
    model = column.prepare({"labels": []})
    assert model is not None
    model.tags.append("custom")
    assert column.process_bind_param(model, dialect()) == {
        "labels": ["custom"]
    }
    table = Table("jsonb_docs", MetaData(), Column("payload", column))
    assert "JSONB" in str(CreateTable(table).compile(dialect=dialect()))
    expression = table.c.payload.contains({"labels": ["custom"]})
    assert "@>" in str(expression.compile(dialect=dialect()))
    copied = column.copy()
    assert getattr(copied.comparator_factory, "__self__") is copied


@dataclass(eq=False)
class SetDocument(Trackable):
    """Contain hashable Trackable models as set members."""

    children: set[DataChild]


@pytest.mark.parametrize(
    "operation", ["add", "update", "symmetric_difference_update"]
)
def test_models_inserted_into_sets_receive_runtime_tracking(
    operation: str,
) -> None:
    """Prepare models introduced through every set-addition entry point.

    Args:
        operation: Set insertion entry point being exercised.
    """
    model: Any = TrackedJSON(SetDocument, fields=DATACLASS_FIELDS).prepare(
        {"children": []}
    )
    child = DataChild()
    getattr(model.children, operation)(
        child if operation == "add" else [child]
    )
    assert child._tracking_parents[model.children._state] == {None}
    child.tags = ["assigned"]
    assert is_trackable(child.tags)
    assert child.tags._tracking_parents[child._state] == {"tags"}


def test_rollback_restores_database_value_and_detaches_mutated_root(
    mapped: tuple[Session, type[Any], type[Any], FieldAccess],
) -> None:
    """Respect normal ORM rollback expiration and reload a fresh tracked graph.

    Args:
        mapped: Isolated ORM and model framework fixture.
    """
    session, row_type, _, _ = mapped
    row = row_type(payload=document_data())
    session.add(row)
    session.commit()
    old = row.payload
    old.title = "rolled back"
    session.flush()
    session.rollback()
    old.child.tags.append("stale")
    assert row not in session.dirty
    assert row.payload.title == "initial"
    row.payload.title = "live"
    assert row in session.dirty


def test_runtime_mutations_enforce_remaining_document_depth() -> None:
    """Measure mutation depth from the column root rather than the incoming value."""

    @dataclass(eq=False)
    class Root(Trackable):
        """Contain a child at depth two and its tags at depth three."""

        child: DataChild

    model: Any = TrackedJSON(
        Root, fields=DATACLASS_FIELDS, max_depth=3
    ).prepare({"child": {"tags": []}})
    tags = model.child.tags
    with pytest.raises(ValueError, match="depth"):
        tags.append([])
    assert tags == []
    with pytest.raises(ValueError, match="depth"):
        model.child.tags = [[]]
    assert model.child.tags is tags
    tags.append("scalar")
    assert tags == ["scalar"]


def test_plain_parameterless_constructor_and_field_deletion() -> None:
    """Restore plain defaults through setters and remove deleted field links."""

    class Defaults(Trackable):
        """Initialize ordinary annotated fields without constructor arguments."""

        tags: list[str]

        def __init__(self) -> None:
            """Initialize the default mutable field before document restoration."""
            self.tags = []

    column = TrackedJSON(Defaults, fields=PLAIN_FIELDS)
    model: Any = column.prepare({"tags": ["stored"]})
    tags = model.tags
    assert tags == ["stored"]
    del model.tags
    assert model._state not in tags._tracking_parents
    model.tags = ["restored"]
    assert model.tags._tracking_parents[model._state] == {"tags"}


def test_plain_model_cannot_deserialize_internal_tracking_metadata() -> None:
    """Reject document keys that would overwrite graph identity or runtime state."""
    column = TrackedJSON(PlainChild, fields=PLAIN_FIELDS)
    with pytest.raises(ValueError, match="reserved"):
        column.prepare({"tags": [], "_state_store": "not a state"})


def test_column_root_preparation_is_silent_and_preserves_plain_aliases() -> (
    None
):
    """Prepare one shared graph without notifications or alias duplication."""
    from typing import ClassVar

    class Observed(Trackable):
        """Record initial-build and subsequent runtime field notifications."""

        events: ClassVar[list[int]] = []

        def __init__(self, first: list[str], second: list[str]) -> None:
            """Store shared raw container references before preparation.

            Args:
                first: First reference to a shared list.
                second: Second reference to that same list.
            """
            self.first = first
            self.second = second

        def _emit_change(self) -> None:
            """Record this node's notification and propagate to its parents."""
            self.events.append(id(self))
            super()._emit_change()

    shared: list[str] = []
    model = Observed(shared, shared)
    prepared: Any = TrackedJSON(Observed, fields=PLAIN_FIELDS).prepare(model)
    assert Observed.events == []
    assert prepared.first is prepared.second
    assert prepared.first._tracking_parents[model._state] == {
        "first",
        "second",
    }
    prepared.first.append("mutation")
    assert Observed.events == [id(model)]
