"""Regression tests for build adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import InitVar, dataclass, field, make_dataclass
from typing import Any, ClassVar

import attrs
import pydantic
import pytest
from pydantic import BaseModel, create_model
from pydantic.v1 import BaseModel as V1BaseModel
from pydantic.v1 import create_model as create_v1_model

from mutrack.adapters.attrs.fields import ATTRS_FIELDS
from mutrack.adapters.dataclasses.fields import DATACLASS_FIELDS
from mutrack.adapters.plain.fields import PLAIN_FIELDS
from mutrack.adapters.pydantic.fields import PYDANTIC_FIELDS
from mutrack.internal.object_access import get_instance_dict, set_stored_field
from mutrack.tracking.build import build_graph
from mutrack.tracking.field_access import CompositeFieldAccess, FieldAccess
from mutrack.tracking.trackable.trackable import Trackable
from tests.graph_support import (
    CONTAINERS,
    Model,
    NeutralDict,
    NeutralList,
    NeutralSet,
)

COMPOSITE = CompositeFieldAccess(
    PYDANTIC_FIELDS, DATACLASS_FIELDS, ATTRS_FIELDS, PLAIN_FIELDS
)


class Observed(Trackable):
    """Record notification identities from framework model fixtures.

    Attributes:
        events: Emitted object identities recorded by the test fixture.
    """

    events: ClassVar[list[int]] = []

    def _emit_change(self) -> None:
        """Propagate a change to live parents."""
        self.events.append(id(self))
        super()._emit_change()


class ActivePydanticModel(Observed, BaseModel):
    """Combine Trackable test observations with the installed Pydantic API."""

    pass


class V1PydanticModel(Observed, V1BaseModel):
    """Use the Pydantic v1 API while preserving validated model identity."""

    class Config:
        """Preserve model identity during Pydantic v1 validation."""

        copy_on_model_validation = "none"


def model_type(kind: str) -> Any:
    """Construct the Trackable model type for a selected framework.

    Args:
        kind: Container or model variant selected for the test.

    Returns:
        The selected framework's Trackable model class.
    """
    if kind == "plain":
        return Model
    names = ("name", "tags", "metadata", "flags", "child", "children", "other")
    if kind == "dataclass":
        return make_dataclass(
            "DataModel",
            [(name, object, field(default=None)) for name in names],
            bases=(Observed,),
            eq=False,
        )
    if kind == "attrs":
        return attrs.make_class(
            "AttrsModel",
            {name: attrs.field(default=None) for name in names},
            bases=(Observed,),
            eq=False,
        )
    if kind == "pydantic.v1":
        return create_v1_model(
            "PydanticGraphModel",
            __base__=V1PydanticModel,
            **dict.fromkeys(names, (object, None)),
        )
    return create_model(
        "PydanticGraphModel",
        __base__=ActivePydanticModel,
        **dict.fromkeys(names, (object, None)),
    )


@pytest.fixture(
    params=["plain", "dataclass", "attrs", "pydantic", "pydantic.v1"]
)
def factory(request: pytest.FixtureRequest) -> Callable[..., Any]:
    """Provide the model constructor selected by the parameterized fixture.

    Args:
        request: Pytest request identifying the selected fixture
            parameter.

    Returns:
        A model constructor for the current fixture parameter.
    """
    return model_type(request.param)


def test_adapter_model_fields_and_nested_propagation(
    factory: Callable[..., Any],
) -> None:
    """Verify adapter model fields and nested propagation.

    Args:
        factory: Constructor supplied by the parameterized model
            fixture.
    """
    address = factory(name="city", tags=[])
    user = factory(
        name="name",
        child=address,
        children=[address, address],
        metadata={"nested": []},
        flags={"flag"},
        tags=[],
    )
    Model.events.clear()
    Observed.events.clear()
    build_graph(user, containers=CONTAINERS, fields=COMPOSITE)

    assert user.name == "name"
    assert user.child is user.children[0] is user.children[1] is address
    assert isinstance(user.tags, NeutralList)
    assert isinstance(user.metadata, NeutralDict)
    assert isinstance(user.flags, NeutralSet)
    assert isinstance(address.tags, NeutralList)
    assert address._tracking_parents[user._state] == {"child"}
    assert address._tracking_parents[user.children._state] == {0, 1}
    assert not Model.events and not Observed.events
    address.tags.append("new")
    events = Model.events + Observed.events
    assert id(address) in events and id(user) in events


def test_adapter_preserves_cross_model_and_cross_field_aliases(
    factory: Callable[..., Any],
) -> None:
    """Verify adapter preserves cross model and cross field aliases.

    Args:
        factory: Constructor supplied by the parameterized model
            fixture.
    """
    child = factory(tags=[])
    user = factory(
        child=child, children=[child, child], tags=[], metadata={}, other=None
    )
    shared: list[object] = []

    for obj, name in ((user, "tags"), (user, "other"), (child, "tags")):
        set_stored_field(obj, name, shared)
    build_graph(user, containers=CONTAINERS, fields=COMPOSITE)

    assert user.tags is user.other is child.tags
    assert user.tags._tracking_parents[user._state] == {"tags", "other"}
    assert user.tags._tracking_parents[child._state] == {"tags"}


def test_mixed_framework_graph() -> None:
    """Verify mixed framework graph."""
    dataclass_type = model_type("dataclass")
    attrs_type = model_type("attrs")
    pydantic_type = model_type("pydantic")
    inner = Model(tags=[])
    address = dataclass_type(child=inner, tags=[])
    alternate = attrs_type(child=address, tags=[])
    root = pydantic_type(children=[alternate], child=address)
    build_graph(root, containers=CONTAINERS, fields=COMPOSITE)

    assert root.children[0] is alternate
    assert alternate.child is address
    assert address.child is inner
    Model.events.clear()
    Observed.events.clear()
    inner.tags.append("new")
    assert id(root) in Observed.events


@pytest.mark.parametrize("family", ["pydantic", "pydantic.v1"])
def test_pydantic_reads_declared_defaults_and_skips_missing_fields(
    family: str,
) -> None:
    """Verify pydantic reads declared defaults and skips missing fields.

    Args:
        family: Pydantic model API selected for the test.
    """
    cls = model_type(family)
    construct = (
        cls.model_construct
        if hasattr(cls, "model_construct")
        else cls.construct
    )
    root = construct(name="name", tags=[], metadata={})
    namespace = get_instance_dict(root)
    assert namespace is not None
    namespace.pop("flags", None)
    namespace["extra"] = []
    namespace["_private"] = []
    before = set(
        root.model_fields_set
        if hasattr(root, "model_fields_set")
        else root.__fields_set__
    )
    build_graph(root, containers=CONTAINERS, fields=PYDANTIC_FIELDS)

    exposed = dict(PYDANTIC_FIELDS.iter_fields(root))
    assert "flags" not in exposed
    assert "extra" not in exposed and "_private" not in exposed
    assert "child" in exposed
    assert type(namespace["extra"]) is list
    after = (
        root.model_fields_set
        if hasattr(root, "model_fields_set")
        else root.__fields_set__
    )
    assert set(after) == before


@pytest.mark.parametrize("family", ["pydantic", "pydantic.v1"])
def test_pydantic_replacement_bypasses_assignment_hooks(family: str) -> None:
    """Verify pydantic replacement bypasses assignment hooks.

    Args:
        family: Pydantic model API selected for the test.
    """
    parent = model_type(family)

    class Guarded(parent):
        """Reject assignment hooks during graph preparation."""

        def __setattr__(self, name: str, value: object) -> None:
            """Reject assignment hooks during raw field replacement.

            Args:
                name: Stored attribute or declared field name.
                value: Value to read, prepare, store, or compare.

            Raises:
                AssertionError: The fixture detects pydantic assignment
                    hook ran.
            """
            raise AssertionError("Pydantic assignment hook ran")

    root = Guarded(tags=[])
    build_graph(root, containers=CONTAINERS, fields=PYDANTIC_FIELDS)
    assert isinstance(root.tags, NeutralList)


@pytest.mark.parametrize("family", ["pydantic", "pydantic.v1"])
def test_pydantic_cyclic_models_restore_fields(family: str) -> None:
    """Verify pydantic cyclic models restore fields.

    Args:
        family: Pydantic model API selected for the test.
    """
    cls = model_type(family)
    root = cls(tags=[], child=None)
    original = root.tags
    set_stored_field(root, "child", root)

    with pytest.raises(ValueError, match="cyclic"):
        build_graph(root, containers=CONTAINERS, fields=PYDANTIC_FIELDS)

    assert root.tags is original
    assert not root._tracking_parents


def test_pydantic_v2_computed_fields_are_not_evaluated() -> None:
    """Verify pydantic v2 computed fields are not evaluated."""
    if not hasattr(pydantic, "computed_field"):
        pytest.skip("Computed fields belong to Pydantic v2.")
    computed_field = pydantic.computed_field

    class Computed(Observed, BaseModel):
        """Expose a computed field that traversal must skip."""

        tags: list[str]

        @computed_field
        @property
        def dangerous(self) -> str:
            """Fail if graph construction evaluates a computed field.

            Returns:
                The stored value if descriptor access is permitted by
                this fixture.

            Raises:
                AssertionError: The fixture detects computed field was
                    accessed.
            """
            raise AssertionError("computed field was accessed")

    root = Computed(tags=[])
    build_graph(root, containers=CONTAINERS, fields=PYDANTIC_FIELDS)
    assert isinstance(root.tags, NeutralList)


def test_dataclass_inheritance_slots_frozen_and_initvar_exclusions() -> None:
    """Verify dataclass inheritance slots frozen and initvar exclusions."""

    @dataclass(frozen=True, slots=True)
    class Parent(Observed):
        """Declare inherited framework fields for adapter regression tests."""

        tags: list[str] = field(default_factory=list)
        ignored: ClassVar[list[object]] = []
        transient: InitVar[int] = 0

    @dataclass(frozen=True, slots=True)
    class Child(Parent):
        """Extend inherited model fields for adapter regression tests."""

        metadata: dict[str, object] = field(default_factory=dict)

    root = Child()
    build_graph(root, containers=CONTAINERS, fields=DATACLASS_FIELDS)
    exposed = dict(DATACLASS_FIELDS.iter_fields(root))

    assert set(exposed) == {"tags", "metadata"}
    assert isinstance(root.tags, NeutralList)
    assert isinstance(root.metadata, NeutralDict)
    assert not DATACLASS_FIELDS.supports(Child)


def test_attrs_frozen_inherited_slots_and_private_init_alias() -> None:
    """Verify attrs frozen inherited slots and private init alias."""

    @attrs.frozen
    class Parent(Observed):
        """Declare inherited framework fields for adapter regression tests."""

        _tags: list[str] = attrs.field(factory=list, alias="tags")

    @attrs.frozen
    class Child(Parent):
        """Extend inherited model fields for adapter regression tests."""

        metadata: dict[str, object] = attrs.field(factory=dict)

    root = Child(tags=[])
    build_graph(root, containers=CONTAINERS, fields=ATTRS_FIELDS)

    assert set(dict(ATTRS_FIELDS.iter_fields(root))) == {"_tags", "metadata"}
    assert isinstance(root._tags, NeutralList)
    assert isinstance(root.metadata, NeutralDict)
    assert root._tags._tracking_parents[root._state] == {"_tags"}
    assert not ATTRS_FIELDS.supports(Child)


def test_attrs_replacement_skips_converters_and_validators() -> None:
    """Verify attrs replacement skips converters and validators."""
    calls: list[object] = []

    def converter(value: object) -> object:
        """Record a converter invocation and return its input unchanged.

        Args:
            value: Value to read, prepare, store, or compare.

        Returns:
            The input value without conversion.
        """
        calls.append(value)
        return value

    @attrs.define
    class Root(Observed):
        """Apply an attrs converter to a tracked field."""

        tags: object = attrs.field(converter=converter)

    root = Root(tags=[])
    calls.clear()
    build_graph(root, containers=CONTAINERS, fields=ATTRS_FIELDS)
    assert not calls
    assert isinstance(root.tags, NeutralList)


@pytest.mark.parametrize(
    "adapter", [PYDANTIC_FIELDS, DATACLASS_FIELDS, ATTRS_FIELDS]
)
def test_adapters_reject_unrelated_roots(adapter: FieldAccess) -> None:
    """Verify adapters reject unrelated roots.

    Args:
        adapter: Field adapter selected for support and root
            validation.
    """
    root = Model(tags=[])
    assert not adapter.supports(root)
    with pytest.raises(TypeError):
        build_graph(root, containers=CONTAINERS, fields=adapter)


def test_composite_uses_first_matching_adapter() -> None:
    """Verify composite uses first matching adapter."""
    root = Model(tags=[])

    class EmptyFields:
        """Match a model without exposing fields to test adapter precedence."""

        def supports(self, obj: object, /) -> bool:
            """Check whether this adapter supports the object instance.

            Args:
                obj: Object whose stored state or fields are accessed.

            Returns:
                True when this adapter can access the object's model
                fields.
            """
            return obj is root

        def iter_fields(self, obj: Any, /) -> list[tuple[str, object]]:
            """Yield available stored model fields.

            Args:
                obj: Object whose stored state or fields are accessed.

            Returns:
                Available field names and their stored values.
            """
            return []

        def set_field(self, obj: Any, name: str, value: object, /) -> None:
            """Replace stored fields without assignment hooks.

            Args:
                obj: Object whose stored state or fields are accessed.
                name: Stored attribute or declared field name.
                value: Value to read, prepare, store, or compare.

            Raises:
                AssertionError: The fixture detects unexpected
                    replacement.
            """
            raise AssertionError("Unexpected replacement")

    build_graph(
        root,
        containers=CONTAINERS,
        fields=CompositeFieldAccess(EmptyFields(), PLAIN_FIELDS),
    )
    assert type(root.tags) is list


@pytest.mark.parametrize("family", ["pydantic", "pydantic.v1"])
def test_typed_address_user_integration(family: str) -> None:
    """Verify typed address user integration.

    Args:
        family: Pydantic model API selected for the test.
    """
    model_base: Any = (
        ActivePydanticModel if family == "pydantic" else V1PydanticModel
    )

    class Address(model_base):
        """Represent an address with a nested mutable tags field."""

        city: str
        tags: list[str]

    class User(model_base):
        """Contain addresses directly and through a collection.

        Attributes:
            name: Stored field name used for replacement and
                restoration.
        """

        name: str
        address: Address
        addresses: list[Address]
        metadata: dict[str, object]

    if hasattr(User, "model_rebuild"):
        User.model_rebuild(_types_namespace={"Address": Address})
    else:
        User.update_forward_refs(Address=Address)
    address = Address(city="Warsaw", tags=[])
    root = User(
        name="User",
        address=address,
        addresses=[address],
        metadata={"nested": []},
    )

    direct = root.address
    listed = root.addresses[0]
    build_graph(root, containers=CONTAINERS, fields=PYDANTIC_FIELDS)

    assert root.address is direct and root.addresses[0] is listed
    assert isinstance(direct.tags, NeutralList)
    assert isinstance(listed.tags, NeutralList)
    Observed.events.clear()
    direct.tags.append("new")
    assert id(root) in Observed.events
    Observed.events.clear()
    listed.tags.append("listed")
    assert id(root) in Observed.events
