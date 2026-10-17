from __future__ import annotations

from typing import Final


PYDANTIC_SKIP_PREFIXES: Final[tuple[str, ...]] = (
    "__pydantic_",
    "_pydantic_",
)

PYDANTIC_ATTRS: Final[frozenset[str]] = frozenset(
    {
        # Pydantic v2
        "model_config",
        "model_fields",
        "model_computed_fields",
        "model_extra",
        "model_fields_set",
        "model_post_init",
        "model_construct",
        "model_copy",
        "model_dump",
        "model_dump_json",
        "model_json_schema",
        "model_validate",
        "model_validate_json",
        "model_validate_strings",
        "model_rebuild",

        # Pydantic v2 internals
        "__pydantic_private__",
        "__pydantic_extra__",
        "__pydantic_fields_set__",

        # Pydantic v1
        "__fields__",
        "__fields_set__",
        "__config__",
        "__validators__",
        "__pre_root_validators__",
        "__post_root_validators__",
        "__schema_cache__",
        "__json_encoder__",
        "__custom_root_type__",
        "__private_attributes__",
        "__values__",

        # Pydantic v1 public API
        "dict",
        "json",
        "copy",
        "parse_obj",
        "parse_raw",
        "parse_file",
        "from_orm",
        "schema",
        "schema_json",
        "construct",
        "validate",
        "update_forward_refs",
    }
)

PYDANTIC_CLASS_ACCESS_ONLY: Final[frozenset[str]] = frozenset(
    {
        # Pydantic v2
        "model_fields",
        "model_config",
        "model_computed_fields",
        "__pydantic_core_schema__",
        "__pydantic_validator__",
        "__pydantic_serializer__",
        "__pydantic_decorators__",
        "__pydantic_generic_metadata__",
        "__pydantic_parent_namespace__",

        # Pydantic v1
        "__fields__",
        "__config__",
        "__validators__",
        "__pre_root_validators__",
        "__post_root_validators__",
        "__schema_cache__",
        "__json_encoder__",
        "__custom_root_type__",

        # Python-generated / framework-generated
        "__signature__",
    }
)
