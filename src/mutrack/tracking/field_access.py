"""Define field access protocols and adapter dispatch."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from mutrack.tracking.trackable.protocols import ITrackable


class FieldAccess(Protocol):
    """Framework field semantics for explicit initial graph construction.

    Implementations expose stored fields and replace their values
    without validation, runtime tracking, or changed() notifications.
    """

    def supports(self, obj: object, /) -> bool:
        """Check whether this adapter supports the object instance.

        Args:
            obj: Object checked for supported model storage.

        Returns:
            True when this adapter can access the object's model
            fields.
        """
        ...

    def iter_fields(self, obj: ITrackable, /) -> Iterable[tuple[str, object]]:
        """Yield available stored model fields.

        Args:
            obj: Supported Trackable model whose fields are read.

        Returns:
            Available field names and their stored values.
        """
        ...

    def set_field(self, obj: ITrackable, name: str, value: object, /) -> None:
        """Replace stored fields without assignment hooks.

        Args:
            obj: Object receiving the raw stored field replacement.
            name: Stored attribute or declared field name.
            value: Replacement value written to storage.
        """
        ...


class CompositeFieldAccess:
    """Dispatch to the first matching caller-supplied adapter.

    Put specialized adapters before broad fallbacks such as plain
    classes. This module never imports optional frameworks or selects
    adapters.
    """

    def __init__(self, *adapters: FieldAccess) -> None:
        """Store adapters in their explicit first-match order.

        Args:
            *adapters: Field adapters in first-match order, with broad
                fallbacks last.
        """
        self._adapters = adapters

    def supports(self, obj: object, /) -> bool:
        """Check whether this adapter supports the object instance.

        Args:
            obj: Object checked for supported model storage.

        Returns:
            True when this adapter can access the object's model
            fields.
        """
        return any(adapter.supports(obj) for adapter in self._adapters)

    def _select(self, obj: object, /) -> FieldAccess:
        """Select the first adapter that supports an object.

        Args:
            obj: Object whose stored state or fields are accessed.

        Returns:
            The first supporting adapter in caller-supplied order.

        Raises:
            TypeError: None of the supplied adapters supports the object.
        """
        for adapter in self._adapters:
            if adapter.supports(obj):
                return adapter
        raise TypeError(f"No field adapter supports {type(obj).__name__}.")

    def iter_fields(self, obj: ITrackable, /) -> Iterable[tuple[str, object]]:
        """Yield available stored model fields.

        Args:
            obj: Supported Trackable model whose fields are read.

        Returns:
            Available field names and their stored values.
        """
        return self._select(obj).iter_fields(obj)

    def set_field(self, obj: ITrackable, name: str, value: object, /) -> None:
        """Replace stored fields without assignment hooks.

        Args:
            obj: Object receiving the raw stored field replacement.
            name: Stored attribute or declared field name.
            value: Replacement value written to storage.
        """
        self._select(obj).set_field(obj, name, value)

    def construct(
        self, model_type: type[Any], values: dict[str, object], /
    ) -> object:
        """Construct through the adapter matching an uninitialized instance.

        Args:
            model_type: Framework model class represented by stored data.
            values: Typed values indexed by stored field name.

        Returns:
            A normally constructed model instance.
        """
        adapter = self._select(object.__new__(model_type))
        factory = getattr(adapter, "construct", None)
        return (
            model_type(**values)
            if factory is None
            else factory(model_type, values)
        )

    def checkpoint(self, obj: ITrackable, /) -> object:
        """Capture optional framework-specific assignment metadata.

        Args:
            obj: Model about to receive an assignment.

        Returns:
            The selected adapter's checkpoint, or None.
        """
        capture = getattr(self._select(obj), "checkpoint", None)
        return None if capture is None else capture(obj)

    def decode_model(
        self,
        model_type: type[Any],
        values: dict[str, object],
        fields: FieldAccess,
        /,
    ) -> object:
        """Delegate native decoding when the selected framework supplies it.

        Args:
            model_type: Model class to reconstruct from JSON data.
            values: Unvalidated JSON object data.
            fields: Outer adapter retained for nested mixed-model decoding.

        Returns:
            A natively decoded model, or None to use annotated decoding.
        """
        adapter = self._select(object.__new__(model_type))
        decode = getattr(adapter, "decode_model", None)
        return None if decode is None else decode(model_type, values, fields)

    def restore_checkpoint(
        self, obj: ITrackable, checkpoint: object, /
    ) -> None:
        """Restore optional framework-specific assignment metadata.

        Args:
            obj: Model whose native assignment failed.
            checkpoint: Previously captured framework metadata.
        """
        restore = getattr(self._select(obj), "restore_checkpoint", None)
        if restore is not None:
            restore(obj, checkpoint)
