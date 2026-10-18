"""Access stored fields for attrs models without assignment hooks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, get_type_hints

import attrs

from mutrack.adapters._fields import StoredFieldAccess
from mutrack.internal.object_access import (
    iter_declared_fields,
    set_stored_field,
)
from mutrack.tracking.field_access import FieldAccess
from mutrack.tracking.serialization import decode_json
from mutrack.tracking.trackable.protocols import ITrackable


class AttrsFieldAccess(StoredFieldAccess):
    """Declared attrs fields, using storage names rather than init aliases."""

    def decode_model(
        self,
        model_type: type[Any],
        values: dict[str, object],
        fields: FieldAccess,
        /,
    ) -> object:
        """Decode typed fields while leaving converter inputs to attrs.

        Args:
            model_type: attrs class reconstructed from the document.
            values: Stored field names or ordinary constructor aliases.
            fields: Outer adapter used for nested mixed-framework models.

        Returns:
            A model processed by its native converters and validators.
        """
        hints = get_type_hints(model_type)
        decoded: dict[str, object] = {}
        for item in attrs.fields(model_type):
            key = item.name if item.name in values else item.alias
            if key in values:
                decoded[item.name] = (
                    values[key]
                    if item.converter is not None
                    else decode_json(
                        values[key], hints.get(item.name, Any), fields
                    )
                )
        return self.construct(model_type, decoded)

    def construct(
        self, model_type: type[Any], values: dict[str, object], /
    ) -> object:
        """Decode storage names through attrs constructor aliases.

        Args:
            model_type: Declared attrs model class.
            values: Decoded stored field names and values.

        Returns:
            A model processed by attrs converters and validators.
        """
        arguments = {
            item.alias: values[item.name]
            for item in attrs.fields(model_type)
            if item.init and item.name in values
        }
        model = model_type(**arguments)
        for item in attrs.fields(model_type):
            if not item.init and item.name in values:
                set_stored_field(
                    model, item.name, values[item.name], create=True
                )
        return model

    def supports(self, obj: object, /) -> bool:
        """Check whether this adapter supports the object instance.

        Args:
            obj: Object checked for supported model storage.

        Returns:
            True when this adapter can access the object's model
            fields.
        """
        return not isinstance(obj, type) and attrs.has(type(obj))

    def iter_fields(self, obj: ITrackable, /) -> Iterable[tuple[str, object]]:
        """Yield available stored model fields.

        Args:
            obj: Supported Trackable model whose fields are read.

        Returns:
            Available field names and their stored values.

        Raises:
            TypeError: The object is not an attrs instance.
        """
        obj_type = type(obj)
        if isinstance(obj, type) or not attrs.has(obj_type):
            raise TypeError("Expected an attrs instance.")
        return iter_declared_fields(
            obj, (item.name for item in attrs.fields(obj_type))
        )


ATTRS_FIELDS = AttrsFieldAccess()
