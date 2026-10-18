"""Share hook-free stored-field replacement across framework adapters."""

from __future__ import annotations

from typing import Any

from mutrack.internal.object_access import set_stored_field
from mutrack.tracking.trackable.protocols import ITrackable


class StoredFieldAccess:
    """Shared hook-free replacement for stored model fields."""

    def construct(
        self, model_type: type[Any], values: dict[str, object], /
    ) -> object:
        """Construct a model using its ordinary keyword constructor.

        Args:
            model_type: Model class to construct after typed decoding.
            values: Decoded values indexed by stored field names.

        Returns:
            A model validated by its normal constructor.
        """
        return model_type(**values)

    def set_field(self, obj: ITrackable, name: str, value: object, /) -> None:
        """Replace stored fields without assignment hooks.

        Args:
            obj: Object receiving the raw stored field replacement.
            name: Stored attribute or declared field name.
            value: Replacement value written to storage.
        """
        set_stored_field(obj, name, value)
