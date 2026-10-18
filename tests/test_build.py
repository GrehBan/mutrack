"""Regression tests for build."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable
from typing import Any, ClassVar

import pytest

from mutrack.adapters.plain.fields import PLAIN_FIELDS, PlainFieldAccess
from mutrack.internal.object_access import set_stored_field
from mutrack.tracking.build import build_graph
from mutrack.tracking.field_access import CompositeFieldAccess
from mutrack.tracking.parents import get_parents_snapshot
from mutrack.tracking.trackable.protocols import ITrackable
from tests.graph_support import (
    CONTAINERS,
    Model,
    NeutralDict,
    NeutralList,
    NeutralSet,
)
from tests.helpers import InputFailure


def build(root: Model, *, limit: int = 100) -> None:
    """Build test graphs using neutral containers and plain fields.

    Args:
        root: Trackable root whose initial graph is constructed.
        limit: Maximum permitted graph depth.
    """
    build_graph(
        root, containers=CONTAINERS, fields=PLAIN_FIELDS, max_depth=limit
    )


def test_plain_scalars_and_all_container_types() -> None:
    """Verify plain scalars and all container types."""
    scalar = object()
    root = Model(
        scalar=scalar, sequence=[1], mapping={"nested": []}, flags={1}
    )
    Model.events.clear()
    build(root)

    assert root.scalar is scalar
    assert isinstance(root.sequence, NeutralList)
    assert isinstance(root.mapping, NeutralDict)
    assert isinstance(root.mapping["nested"], NeutralList)
    assert isinstance(root.flags, NeutralSet)
    assert root.sequence._tracking_parents[root._state] == {"sequence"}
    assert root.mapping["nested"]._tracking_parents[root.mapping._state] == {
        "nested"
    }
    assert Model.events == []


@pytest.mark.parametrize("existing", [False, True])
def test_nested_models_in_containers_and_duplicate_indices(
    existing: bool,
) -> None:
    """Verify nested models in containers and duplicate indices.

    Args:
        existing: Whether the input container is already Trackable.
    """
    address = Model(tags=[])
    children = (
        NeutralList([address, address]) if existing else [address, address]
    )
    root = Model(
        address=address, addresses=children, metadata={"child": address}
    )
    build(root)

    assert root.address is address
    assert root.addresses[0] is root.addresses[1] is address
    if existing:
        assert root.addresses is children
    assert address._tracking_parents[root._state] == {"address"}
    assert address._tracking_parents[root.addresses._state] == {0, 1}
    assert address._tracking_parents[root.metadata._state] == {"child"}
    Model.events.clear()
    address.tags.append("new")
    assert id(address) in Model.events
    assert id(root) in Model.events


@pytest.mark.parametrize("kind", ["list", "dict", "set"])
def test_existing_containers_discover_models_without_rewrapping(
    kind: str,
) -> None:
    """Verify existing containers discover models without rewrapping.

    Args:
        kind: Container or model variant selected for the test.
    """
    child = Model(tags=[])
    containers: dict[str, Any] = {
        "list": NeutralList([child]),
        "dict": NeutralDict({"child": child}),
        "set": NeutralSet({child}),
    }
    value = containers[kind]
    root = Model(value=value)
    build(root)

    assert root.value is value
    assert isinstance(child.tags, NeutralList)
    assert child._tracking_parents[value._state] == {
        {"list": 0, "dict": "child", "set": None}[kind]
    }


def test_existing_container_plain_contents_are_left_untouched() -> None:
    """Verify existing container plain contents are left untouched."""
    plain: list[int] = []
    value = NeutralList([plain])
    root = Model(value=value)
    build(root)

    assert root.value is value and value[0] is plain


def test_cross_field_and_cross_model_container_aliases() -> None:
    """Verify cross field and cross model container aliases."""
    shared: list[object] = []
    nested = Model(value=shared)
    root = Model(first=shared, nested=nested, second={"shared": shared})
    build(root)

    assert root.first is nested.value is root.second["shared"]
    assert root.first._tracking_parents[root._state] == {"first"}
    assert root.first._tracking_parents[nested._state] == {"value"}


@pytest.mark.parametrize("kind", ["self", "mutual", "container", "plain"])
def test_cycles_restore_all_replaced_fields(kind: str) -> None:
    """Verify cycles restore all replaced fields.

    Args:
        kind: Container or model variant selected for the test.
    """
    original: list[int] = [1]
    root = Model(first=original)
    other = Model(tags=[])
    if kind == "self":
        setattr(root, "cycle", root)
    elif kind == "mutual":
        setattr(root, "cycle", other)
        setattr(other, "cycle", root)
    elif kind == "container":
        setattr(root, "cycle", [other])
        setattr(other, "cycle", root)
    else:
        cyclic: list[object] = []
        cyclic.append(cyclic)
        setattr(root, "cycle", cyclic)
    Model.events.clear()

    with pytest.raises(ValueError, match="cyclic"):
        build(root)

    assert root.first is original
    assert not root._tracking_parents
    assert not other._tracking_parents
    assert type(other.tags) is list
    assert Model.events == []


@pytest.mark.parametrize("deeper_first", [False, True])
def test_global_depth_checks_shared_models_on_every_path(
    deeper_first: bool,
) -> None:
    """Verify global depth checks shared models on every path.

    Args:
        deeper_first: Whether the deeper shared-model path is visited
            first.
    """
    shared = Model(tags=[])
    deep = Model(child=shared)
    root = (
        Model(first=deep, second=shared)
        if deeper_first
        else Model(first=shared, second=deep)
    )

    with pytest.raises(ValueError, match="max depth"):
        build(root, limit=3)

    assert type(shared.tags) is list
    assert not shared._tracking_parents
    build(root, limit=4)
    assert isinstance(shared.tags, NeutralList)


def test_graph_depth_includes_models_and_container_edges() -> None:
    """Verify graph depth includes models and container edges."""
    root = Model(children=[Model(tags=[])])
    with pytest.raises(ValueError, match="max depth"):
        build(root, limit=3)
    build(root, limit=4)


def test_zero_negative_default_and_unsupported_root() -> None:
    """Verify zero negative default and unsupported root."""

    class Limited(Model):
        """Apply a small graph-depth limit for boundary validation.

        Attributes:
            _max_depth_limit: Default nesting limit used when callers
                omit max_depth.
        """

        _max_depth_limit: ClassVar[int] = 1

    root = Limited(tags=[])
    with pytest.raises(ValueError, match="max depth"):
        build_graph(root, containers=CONTAINERS, fields=PLAIN_FIELDS)
    for limit in (-1, 0):
        with pytest.raises(ValueError):
            build(root, limit=limit)
    with pytest.raises(TypeError):
        build_graph(root, containers=CONTAINERS, fields=CompositeFieldAccess())
    with pytest.raises(TypeError):
        build_graph(NeutralList(), containers=CONTAINERS, fields=PLAIN_FIELDS)
    invalid: Any = object()
    with pytest.raises(TypeError):
        build_graph(invalid, containers=CONTAINERS, fields=PLAIN_FIELDS)


def test_build_is_idempotent_and_preserves_external_links() -> None:
    """Verify build is idempotent and preserves external links."""
    child = Model(tags=[])
    external = Model()
    external._state.link(child, "outside")
    root = Model(child=child)
    build(root)
    tags = child.tags
    before = get_parents_snapshot(child)
    Model.events.clear()
    build(root)

    assert child.tags is tags
    assert get_parents_snapshot(child) == before
    assert child._tracking_parents[external._state] == {"outside"}
    assert Model.events == []


def test_link_failure_rolls_back_container_internals_and_field_assignments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify link failures restore containers and fields.

    Args:
        monkeypatch: Pytest fixture that restores temporary method
            replacements.

    Raises:
        InputFailure: The fixture detects commit failed.
    """
    from mutrack.tracking.graph.linking import transaction

    child = Model()
    original = [child]
    root = Model(first=original, fail=Model())
    external = Model()
    external._state.link(child, "existing")
    before = get_parents_snapshot(child)
    link = transaction.link_child
    unlinks: list[object] = []
    unlink = transaction.unlink_child

    def failing_link(parent: ITrackable, value: ITrackable, key: Any) -> bool:
        """Inject the configured link failure while committing a test graph.

        Args:
            parent: Trackable owner of the child reference.
            value: Value to read, prepare, store, or compare.
            key: Field name, container key, list index, or None for a
                set member.

        Returns:
            Whether the delegated graph link was newly created.

        Raises:
            InputFailure: The fixture detects commit failed.
        """
        if key == "fail":
            raise InputFailure("commit failed")
        return link(parent, value, key)

    def record_unlink(parent: ITrackable, value: ITrackable, key: Any) -> bool:
        """Record rollback order before delegating to physical unlinking.

        Args:
            parent: Trackable owner of the child reference.
            value: Value to read, prepare, store, or compare.
            key: Field name, container key, list index, or None for a
                set member.

        Returns:
            Whether the recorded reference was removed.
        """
        unlinks.append(key)
        return unlink(parent, value, key)

    monkeypatch.setattr(transaction, "link_child", failing_link)
    monkeypatch.setattr(transaction, "unlink_child", record_unlink)
    Model.events.clear()
    with pytest.raises(InputFailure, match="commit failed"):
        build(root)

    assert root.first is original
    assert get_parents_snapshot(child) == before
    assert not root.fail._tracking_parents
    assert unlinks == ["first", 0]
    assert Model.events == []


@pytest.mark.parametrize("failure", ["enumerate", "replace"])
def test_adapter_failure_restores_fields_and_never_commits(
    failure: str,
) -> None:
    """Verify adapter failure restores fields and never commits.

    Args:
        failure: Adapter failure stage selected for the regression
            test.
    """

    class FailingFields(PlainFieldAccess):
        """Inject field access failures for rollback tests."""

        def iter_fields(
            self, obj: ITrackable, /
        ) -> Iterable[tuple[str, object]]:
            """Yield available stored model fields.

            Args:
                obj: Object whose stored state or fields are accessed.

            Returns:
                Available field names and their stored values.

            Raises:
                InputFailure: The fixture detects enumeration failed.
            """
            if obj is nested and failure == "enumerate":
                raise InputFailure("enumeration failed")
            return super().iter_fields(obj)

        def set_field(
            self, obj: ITrackable, name: str, value: object, /
        ) -> None:
            """Replace stored fields without assignment hooks.

            Args:
                obj: Object whose stored state or fields are accessed.
                name: Stored attribute or declared field name.
                value: Value to read, prepare, store, or compare.

            Raises:
                InputFailure: The fixture detects replacement failed
                    after write.
            """
            super().set_field(obj, name, value)
            if name == "bad" and isinstance(value, NeutralList):
                raise InputFailure("replacement failed after write")

    first = [Model()]
    bad: list[int] = []
    nested = Model(bad=bad)
    root = Model(first=first, nested=nested)
    with pytest.raises(InputFailure):
        build_graph(root, containers=CONTAINERS, fields=FailingFields())

    assert root.first is first and nested.bad is bad
    assert not first[0]._tracking_parents
    assert not nested._tracking_parents


def test_build_never_calls_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify build never calls changed.

    Args:
        monkeypatch: Pytest fixture that restores temporary method
            replacements.

    Raises:
        AssertionError: The fixture detects changed called during
            build.
    """

    def forbidden(self: object) -> None:
        """Fail if initial graph construction invokes a change notification.

        Raises:
            AssertionError: The fixture detects changed called during
                build.
        """
        raise AssertionError("changed called during build")

    for cls in (Model, NeutralList, NeutralDict, NeutralSet):
        monkeypatch.setattr(cls, "changed", forbidden)
    build(Model(child=Model(tags=[]), mapping={"nested": []}, flags={1}))


def test_unsupported_nested_trackable_is_an_opaque_leaf() -> None:
    """Verify unsupported nested trackable is an opaque leaf."""

    class OnlyRoot(PlainFieldAccess):
        """Support only the root and leave nested Trackables opaque."""

        def supports(self, obj: object, /) -> bool:
            """Check whether this adapter supports the object instance.

            Args:
                obj: Object whose stored state or fields are accessed.

            Returns:
                True when this adapter can access the object's model
                fields.
            """
            return obj is root

    nested = Model(tags=[])
    root = Model(child=nested)
    build_graph(root, containers=CONTAINERS, fields=OnlyRoot())
    assert nested._tracking_parents[root._state] == {"child"}
    assert type(nested.tags) is list


def test_plain_writes_bypass_shadowing_properties_and_assignment_hooks() -> (
    None
):
    """Verify plain writes bypass shadowing properties and assignment hooks."""

    class Base(Model):
        """Declare base storage for this regression test."""

        __slots__ = ("child",)

    class Derived(Base):
        """Shadow inherited storage for descriptor bypass tests."""

        @property
        def child(self) -> object:
            """Fail if field access invokes the shadowing child property.

            Returns:
                The stored value if descriptor access is permitted by
                this fixture.

            Raises:
                AssertionError: The fixture detects property read.
            """
            raise AssertionError("property read")

        @child.setter
        def child(self, value: object) -> None:
            """Fail if field access invokes the shadowing child property.

            Args:
                value: Value to read, prepare, store, or compare.

            Raises:
                AssertionError: The fixture detects property write.
            """
            raise AssertionError("property write")

        def __setattr__(self, name: str, value: object) -> None:
            """Reject assignment hooks during raw field replacement.

            Args:
                name: Stored attribute or declared field name.
                value: Value to read, prepare, store, or compare.

            Raises:
                AssertionError: The fixture detects assignment hook.
            """
            raise AssertionError("assignment hook")

    obj = Derived()
    Base.__dict__["child"].__set__(obj, [])
    build(obj)
    stored = Base.__dict__["child"].__get__(obj)
    assert isinstance(stored, NeutralList)
    assert stored._tracking_parents[obj._state] == {"child"}


def test_missing_stored_field_cannot_invoke_a_property() -> None:
    """Verify missing stored field cannot invoke a property."""

    class PropertyOnly:
        """Expose a computed property without matching writable storage."""

        @property
        def value(self) -> object:
            """Fail if field access invokes a computed value property.

            Returns:
                The stored value if descriptor access is permitted by
                this fixture.

            Raises:
                AssertionError: The fixture detects property read.
            """
            raise AssertionError("property read")

    with pytest.raises(AttributeError):
        set_stored_field(PropertyOnly(), "value", [])


def test_plain_adapter_reads_slots_declared_by_consumed_iterator() -> None:
    """Verify plain adapter reads slots declared by consumed iterator."""

    class Slotted(Model):
        """Expose declared slots for descriptor-safe field access tests."""

        __slots__ = iter(("value",))

    root = Slotted(value=[])
    build(root)

    assert isinstance(root.value, NeutralList)
    assert root.value._tracking_parents[root._state] == {"value"}


def test_core_build_has_no_framework_imports() -> None:
    """Verify core build has no framework imports."""
    script = """
import sys
class BlockFrameworks:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sqlalchemy', 'pydantic', 'attrs', 'attr'}:
            raise AssertionError('Framework import: ' + fullname)
sys.meta_path.insert(0, BlockFrameworks())
from mutrack.tracking.build import build_graph
from mutrack.adapters.plain.fields import PLAIN_FIELDS
from tests.graph_support import CONTAINERS, Model, NeutralList
root = Model(child=Model(tags=[]))
build_graph(root, containers=CONTAINERS, fields=PLAIN_FIELDS)
assert isinstance(root.child.tags, NeutralList)
root.child.tags.append('new')
assert id(root) in Model.events
"""
    subprocess.run([sys.executable, "-c", script], check=True, timeout=30)
