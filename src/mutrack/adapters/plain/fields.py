"""Access stored fields for plain models without assignment hooks."""

from __future__ import annotations

from collections.abc import Iterable
from inspect import Parameter, signature
from typing import Any

from mutrack.adapters._fields import StoredFieldAccess
from mutrack.internal.object_access import (
    get_instance_dict,
    iter_slot_descriptors,
)
from mutrack.introspection.atomic import is_atomic
from mutrack.introspection.fields import iter_object_fields
from mutrack.tracking.trackable.protocols import ITrackable


class PlainFieldAccess(StoredFieldAccess):
    """Stored instance fields and inherited slots; no computed properties.

    This broad adapter belongs last in a CompositeFieldAccess.
    """

    def construct(
        self, model_type: type[Any], values: dict[str, object], /
    ) -> object:
        """Construct ordinary classes and restore remaining fields via setters.

        Args:
            model_type: Plain class whose constructor initializes defaults.
            values: Decoded stored field names and values.

        Returns:
            A model processed by its native constructor and assignment hooks.
        """
        parameters = signature(model_type).parameters
        if any(p.kind is Parameter.VAR_KEYWORD for p in parameters.values()):
            return model_type(**values)
        arguments = {
            name: value
            for name, value in values.items()
            if name in parameters
            and parameters[name].kind
            in (Parameter.POSITIONAL_OR_KEYWORD, Parameter.KEYWORD_ONLY)
        }
        model = model_type(**arguments)
        for name, value in values.items():
            if name not in arguments:
                setattr(model, name, value)
        return model

    def supports(self, obj: object, /) -> bool:
        """Check whether this adapter supports the object instance.

        Args:
            obj: Object checked for supported model storage.

        Returns:
            True when this adapter can access the object's model
            fields.
        """
        if isinstance(obj, (type, list, dict, set, tuple)) or is_atomic(obj):
            return False
        return get_instance_dict(obj) is not None or any(
            True for _ in iter_slot_descriptors(obj)
        )

    def iter_fields(self, obj: ITrackable, /) -> Iterable[tuple[str, object]]:
        """Yield available stored model fields.

        Args:
            obj: Supported Trackable model whose fields are read.

        Returns:
            Available field names and their stored values.

        Raises:
            TypeError: An argument or object does not meet the required
                protocol.
        """
        if not self.supports(obj):
            raise TypeError("Expected a plain object with instance storage.")
        return iter_object_fields(obj)


PLAIN_FIELDS = PlainFieldAccess()
