"""Persist adapter-backed models and notify ORM columns on mutation."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Generic, Self, TypeVar, cast
from weakref import ref

from sqlalchemy import JSON, event
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapper, attributes
from sqlalchemy.orm.state import InstanceState
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.operators import OperatorType
from sqlalchemy.types import TypeDecorator, TypeEngine

from mutrack.adapters.sqlalchemy.collections.registry import (
    get_sqlalchemy_containers,
)
from mutrack.tracking.build import build_graph
from mutrack.tracking.field_access import FieldAccess
from mutrack.tracking.runtime import TrackingOptions, configure_graph
from mutrack.tracking.serialization import (
    decode_json,
    encode_json,
    validate_json_input,
)
from mutrack.tracking.trackable.protocols import ITrackable, is_trackable
from mutrack.tracking.trackable.trackable import Trackable

ModelT = TypeVar("ModelT", bound=ITrackable)
_OBSERVERS = "mutrack.column_observers"


class TrackedJSON(TypeDecorator[ModelT], Generic[ModelT]):
    """Store a Trackable model using an explicit field adapter and JSON type.

    Both typed model assignments and mapping inputs are prepared. Mutation
    hooks are enabled per instance while retaining native framework setters.
    Custom encoders and decoders can implement application-specific schemas.
    """

    impl: TypeEngine[Any] | type[TypeEngine[Any]] = JSON()
    cache_ok = False

    def __init__(
        self,
        model_type: type[ModelT],
        /,
        *,
        fields: FieldAccess,
        encode: Callable[[ModelT], object] | None = None,
        decode: Callable[[object], ModelT] | None = None,
        storage: TypeEngine[Any] | None = None,
        max_depth: int | None = None,
    ) -> None:
        """Configure document serialization and graph preparation.

        Args:
            model_type: Trackable application model stored in this column.
            fields: Single-framework or composite field adapter.
            encode: Optional model-to-JSON conversion callback.
            decode: Optional JSON-to-model conversion callback.
            storage: JSON-compatible SQLAlchemy type, such as JSONB.
            max_depth: Graph limit, defaulting to the model's own limit.

        Raises:
            ValueError: The configured depth limit is negative.
        """
        super().__init__()
        self.model_type = model_type
        self.fields = fields
        self.encoder = encode
        self.decoder = decode
        self.max_depth = max_depth
        if max_depth is not None and max_depth < 0:
            raise ValueError("Column max depth cannot be negative.")
        if storage is not None:
            self.impl = storage
        self.comparator_factory = self._document_comparator

    @property
    def python_type(self) -> type[ModelT]:
        """Return the application model type represented by this SQL type.

        Returns:
            The configured Trackable model class.
        """
        return self.model_type

    def _document_comparator(
        self, expr: ColumnElement[Any]
    ) -> TypeEngine.Comparator[Any]:
        """Retain dialect operators and return raw JSON for path selections.

        Args:
            expr: Document column expression receiving a comparator.

        Returns:
            A storage-compatible comparator with JSON-typed path results.
        """
        base = type(self.impl_instance.comparator_factory(expr))
        bases = (
            (base,)
            if issubclass(base, TypeDecorator.Comparator)
            else (TypeDecorator.Comparator, base)
        )

        def getitem(
            comparator: Any, index: Any
        ) -> tuple[OperatorType, Any, TypeEngine[Any]]:
            """Bind a JSON path and select the underlying result type.

            Args:
                comparator: SQLAlchemy comparator for the document column.
                index: JSON object key, array index, or path tuple.

            Returns:
                Operator, bound index expression, and raw JSON result type.
            """
            operator, expression, _ = getattr(base, "_setup_getitem")(
                comparator, index
            )
            return operator, expression, self.impl_instance

        comparator_type = type(
            "DocumentComparator", bases, {"_setup_getitem": getitem}
        )
        return cast(TypeEngine.Comparator[Any], comparator_type(expr))

    def prepare(self, value: object) -> ModelT | None:
        """Decode and initialize a column value before ORM ownership attaches.

        Args:
            value: Existing model, mapping input, or None.

        Returns:
            The prepared model, preserving existing model identity, or None.

        Raises:
            TypeError: Decoding did not produce a supported Trackable model.
        """
        if value is None:
            return None
        model = value
        if not isinstance(model, self.model_type):
            validate_json_input(
                model,
                self.model_type._max_depth_limit
                if self.max_depth is None
                else self.max_depth,
            )
            model = (
                decode_json(model, self.model_type, self.fields)
                if self.decoder is None
                else self.decoder(model)
            )
        if not isinstance(model, self.model_type) or not is_trackable(model):
            raise TypeError(
                "Column values must match the model and ITrackable."
            )
        limit = (
            model._max_depth_limit
            if self.max_depth is None
            else self.max_depth
        )
        options = TrackingOptions(
            self.fields, get_sqlalchemy_containers(), limit
        )
        configure_graph([model], options)
        build_graph(
            model,
            containers=options.containers,
            fields=self.fields,
            max_depth=limit,
        )
        configure_graph([model], options)
        return cast(ModelT, model)

    def process_bind_param(
        self, value: ModelT | None, dialect: Dialect
    ) -> object:
        """Encode application fields without graph or ORM bookkeeping.

        Args:
            value: Prepared model being written, or None.
            dialect: SQLAlchemy database dialect performing the bind.

        Returns:
            JSON-compatible application data, or None.
        """
        if value is None:
            return None
        return (
            encode_json(value, self.fields)
            if self.encoder is None
            else self.encoder(value)
        )

    def copy(self, **kw: Any) -> Self:
        """Keep comparator callbacks bound to the copied SQLAlchemy type.

        Args:
            **kw: SQLAlchemy type-copy options forwarded to the base class.

        Returns:
            A type copy retaining this column's model and codec configuration.
        """
        copied = super().copy(**kw)
        copied.comparator_factory = copied._document_comparator
        return copied

    def process_result_value(
        self, value: object, dialect: Dialect
    ) -> ModelT | None:
        """Initialize models before ORM load events attach their owners.

        Args:
            value: Decoded JSON tree received from the database.
            dialect: SQLAlchemy database dialect processing the result.

        Returns:
            A live tracked model ready for nested mutations, or None.
        """
        return self.prepare(value)

    def coerce_compared_value(
        self, op: OperatorType | None, value: Any
    ) -> TypeEngine[Any]:
        """Preserve the storage type's JSON indexing and comparison coercion.

        Args:
            op: SQL expression operator being applied.
            value: Other side of the SQL expression.

        Returns:
            The underlying JSON type's comparison coercion result.
        """
        if isinstance(value, self.model_type):
            return self
        return self.impl_instance.coerce_compared_value(op, value)


class _ColumnObserver(Trackable):
    """Hold a weak ORM owner and bridge model notifications to its column."""

    def __init__(self, state: InstanceState[Any], key: str) -> None:
        """Remember the ORM state without retaining its mapped instance.

        Args:
            state: Mapped instance state that owns this column.
            key: Mapped attribute receiving nested mutation notifications.
        """
        self.owner = ref(state)
        self.key = key
        self.root: ref[ITrackable] | None = None

    def attach(self, value: ITrackable | None) -> None:
        """Replace the observed graph root while preserving other owners.

        Args:
            value: New root, or None when ownership ends.
        """
        old = None if self.root is None else self.root()
        if old is value:
            return
        if value is not None:
            self._state.link(value, self.key)
        if old is not None:
            self._state.unlink(old, self.key)
        self.root = None if value is None else ref(value)

    def _emit_change(self) -> None:
        """Flag the ORM column only while it still holds this observed root."""
        state = self.owner()
        value = None if self.root is None else self.root()
        if state is not None and value is not None:
            owner = state.obj()
            if owner is not None and state.dict.get(self.key) is value:
                attributes.flag_modified(owner, self.key)


def _observer(state: InstanceState[Any], key: str) -> _ColumnObserver:
    """Retrieve an observer retained by the ORM state rather than its child.

    Args:
        state: Mapped owner state.
        key: Mapped column attribute name.

    Returns:
        The unique observer for this state and column.
    """
    observers = state.info.setdefault(_OBSERVERS, {})
    if key not in observers:
        observers[key] = _ColumnObserver(state, key)
    return cast(_ColumnObserver, observers[key])


def _listen(cls: type[Any], key: str, column: TrackedJSON[Any]) -> None:
    """Register assignment, reload, expiration, and merge ownership hooks.

    Args:
        cls: Mapped ORM class declaring the document column.
        key: Document attribute key.
        column: Document type handling validation and graph initialization.
    """

    def assign(
        state: InstanceState[Any], value: object, old: object, token: object
    ) -> object:
        """Prepare even typed assignments before replacing ownership.

        Args:
            state: Mapped owner state receiving an assignment.
            value: New typed model, mapping, or None.
            old: Previous attribute value supplied by SQLAlchemy.
            token: SQLAlchemy attribute event token.

        Returns:
            The prepared model or None to store in the mapped attribute.
        """
        prepared = column.prepare(value)
        _observer(state, key).attach(prepared)
        return prepared

    def load(state: InstanceState[Any], *args: object) -> None:
        """Attach already prepared values after ORM loading or merging.

        Args:
            state: Loaded or merged ORM instance state.
            *args: Additional SQLAlchemy event context.
        """
        value = state.dict.get(key)
        prepared = column.prepare(value)
        if key in state.dict:
            state.dict[key] = prepared
        _observer(state, key).attach(prepared)

    def refresh(
        state: InstanceState[Any], context: object, attrs: Iterable[str] | None
    ) -> None:
        """Reattach the column when a refresh includes its attribute.

        Args:
            state: Refreshed ORM instance state.
            context: SQLAlchemy refresh context.
            attrs: Refreshed attribute names, or None for all attributes.
        """
        if attrs is None or key in attrs:
            load(state)

    def expire(state: InstanceState[Any], attrs: Iterable[str] | None) -> None:
        """Detach stale document roots when their mapped column expires.

        Args:
            state: ORM instance whose attributes expired.
            attrs: Expired attribute names, or None for all attributes.
        """
        if attrs is None or key in attrs:
            _observer(state, key).attach(None)

    event.listen(
        getattr(cls, key), "set", assign, raw=True, retval=True, propagate=True
    )
    event.listen(cls, "load", load, raw=True, propagate=True)
    event.listen(cls, "refresh", refresh, raw=True, propagate=True)
    event.listen(cls, "refresh_flush", refresh, raw=True, propagate=True)
    event.listen(cls, "expire", expire, raw=True, propagate=True)
    event.listen(
        cls, "_sa_event_merge_wo_load", load, raw=True, propagate=True
    )


@event.listens_for(Mapper, "mapper_configured")
def _configure_mapper(mapper: Mapper[Any], cls: type[Any]) -> None:
    """Attach observers only to attributes declaring TrackedJSON columns.

    Args:
        mapper: Newly configured SQLAlchemy mapper.
        cls: Mapped ORM class associated with the mapper.
    """
    for prop in mapper.column_attrs:
        if prop.parent is mapper and len(prop.columns) == 1:
            column = prop.columns[0].type
            if isinstance(column, TrackedJSON):
                _listen(cls, prop.key, column)
