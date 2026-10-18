"""Access stored fields for pydantic models without assignment hooks."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from inspect import signature
from typing import Any, cast

from pydantic import BaseModel
from pydantic.v1 import BaseModel as V1BaseModel

from mutrack.adapters._fields import StoredFieldAccess
from mutrack.internal.object_access import (
    iter_declared_fields,
    raw_getattr,
    raw_setattr,
)
from mutrack.tracking.field_access import FieldAccess
from mutrack.tracking.trackable.protocols import ITrackable


class PydanticFieldAccess(StoredFieldAccess):
    """Available declared fields in Pydantic v1, v2, or pydantic.v1.

    Defaults are included, even when not explicitly supplied. Extras,
    computed fields, and private metadata are excluded. Raw replacement
    preserves validation and fields-set metadata without assignment
    hooks.
    """

    def construct(
        self, model_type: type[Any], values: dict[str, object], /
    ) -> object:
        """Validate stored field names through the active Pydantic API.

        Args:
            model_type: Pydantic v1 or v2 model class.
            values: Decoded values using actual field names.

        Returns:
            A validated model, honoring native model validators.
        """
        if issubclass(model_type, V1BaseModel):
            aliases = dict(values)
            for name, item in model_type.__fields__.items():
                if name in aliases and item.alias != name:
                    aliases[item.alias] = aliases.pop(name)
            return model_type.parse_obj(aliases)
        if "by_name" in signature(model_type.model_validate).parameters:
            return model_type.model_validate(values, by_name=True)
        aliases = dict(values)
        for name, item in model_type.model_fields.items():
            alias = item.validation_alias or item.alias
            if name not in aliases or alias is None:
                continue
            if not isinstance(alias, str):
                raise ValueError(
                    "This Pydantic alias requires a custom document decoder."
                )
            aliases[alias] = aliases.pop(name)
        return model_type.model_validate(aliases)

    def decode_model(
        self,
        model_type: type[Any],
        values: dict[str, object],
        fields: FieldAccess,
        /,
    ) -> object:
        """Delegate typed decoding to Pydantic's own validators.

        Args:
            model_type: Model class represented by the incoming document.
            values: Unvalidated field data or serialized stored field data.
            fields: Outer adapter used by mixed-framework document decoding.

        Returns:
            A natively validated Pydantic model.
        """
        return self.construct(model_type, values)

    def checkpoint(self, obj: ITrackable, /) -> object:
        """Copy fields-set metadata before a tracked assignment.

        Args:
            obj: Pydantic model receiving an ordinary assignment.

        Returns:
            Storage name and a copy of the fields-set metadata.
        """
        name = (
            "__fields_set__"
            if isinstance(obj, V1BaseModel)
            else "__pydantic_fields_set__"
        )
        return name, set(cast("set[str]", raw_getattr(obj, name)))

    def restore_checkpoint(self, obj: ITrackable, checkpoint: Any, /) -> None:
        """Restore fields-set metadata after assignment rollback.

        Args:
            obj: Pydantic model whose assignment failed.
            checkpoint: Previously copied metadata and its storage name.
        """
        name, value = checkpoint
        raw_setattr(obj, name, value)

    def supports(self, obj: object, /) -> bool:
        """Check whether this adapter supports the object instance.

        Args:
            obj: Object checked for supported model storage.

        Returns:
            True when this adapter can access the object's model
            fields.
        """
        return isinstance(obj, (BaseModel, V1BaseModel))

    def iter_fields(self, obj: ITrackable, /) -> Iterable[tuple[str, object]]:
        """Yield available stored model fields.

        Args:
            obj: Supported Trackable model whose fields are read.

        Returns:
            Available field names and their stored values.

        Raises:
            TypeError: The object is not a Pydantic BaseModel instance.
        """
        declared: Mapping[str, object]
        if isinstance(obj, V1BaseModel):
            declared = type(obj).__fields__
        elif isinstance(obj, BaseModel):
            declared = type(obj).model_fields
        else:
            raise TypeError("Expected a Pydantic BaseModel instance.")
        return iter_declared_fields(obj, declared)


PYDANTIC_FIELDS = PydanticFieldAccess()
