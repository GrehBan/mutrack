"""Access stored fields for dataclasses models without assignment hooks."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import fields, is_dataclass
from typing import Any

from mutrack.adapters._fields import StoredFieldAccess
from mutrack.internal.object_access import (
    iter_declared_fields,
    set_stored_field,
)
from mutrack.tracking.trackable.protocols import ITrackable


class DataclassFieldAccess(StoredFieldAccess):
    """Declared dataclass instance fields, excluding InitVar and ClassVar."""

    def construct(
        self, model_type: type[Any], values: dict[str, object], /
    ) -> object:
        """Construct through init fields and restore persisted non-init fields.

        Args:
            model_type: Dataclass document class to reconstruct.
            values: Decoded values indexed by declared storage names.

        Returns:
            A normally constructed dataclass with persisted fields restored.
        """
        declared = fields(model_type)
        model = model_type(
            **{
                item.name: values[item.name]
                for item in declared
                if item.init and item.name in values
            }
        )
        for item in declared:
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
        return not isinstance(obj, type) and is_dataclass(obj)

    def iter_fields(self, obj: ITrackable, /) -> Iterable[tuple[str, object]]:
        """Yield available stored model fields.

        Args:
            obj: Supported Trackable model whose fields are read.

        Returns:
            Available field names and their stored values.

        Raises:
            TypeError: The object is not a dataclass instance.
        """
        if isinstance(obj, type) or not is_dataclass(obj):
            raise TypeError("Expected a dataclass instance.")
        return iter_declared_fields(obj, (item.name for item in fields(obj)))


DATACLASS_FIELDS = DataclassFieldAccess()
