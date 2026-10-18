"""Regression tests for fields."""

from __future__ import annotations

from mutrack.introspection.fields import iter_object_fields
from tests.helpers import TrackedValue


def test_shadowed_inherited_slot_bypasses_property() -> None:
    """Verify shadowed inherited slot bypasses property."""

    class Base:
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
                AssertionError: The fixture detects property must not
                    run.
            """
            raise AssertionError("property must not run")

    obj = Derived()
    child = TrackedValue()
    Base.__dict__["child"].__set__(obj, child)

    assert dict(iter_object_fields(obj)) == {"child": child}


def test_slot_descriptor_replaced_by_property_is_not_invoked() -> None:
    """Verify slot descriptor replaced by property is not invoked.

    Raises:
        AssertionError: The fixture detects property must not run.
    """

    class Slotted:
        """Expose declared slots for descriptor-safe field access tests."""

        __slots__ = ("child",)

    def fail(obj: object) -> object:
        """Fail if traversal evaluates the user descriptor under test.

        Args:
            obj: Object whose stored state or fields are accessed.

        Returns:
            The stored value if descriptor access is permitted by this
            fixture.

        Raises:
            AssertionError: The fixture detects property must not run.
        """
        raise AssertionError("property must not run")

    setattr(Slotted, "child", property(fail))
    assert not list(iter_object_fields(Slotted()))


def test_private_inherited_unset_and_internal_slots() -> None:
    """Verify private inherited unset and internal slots."""

    class Base:
        """Declare base storage for this regression test."""

        __slots__ = ("__child", "unset", "_sa_internal")

    class Derived(Base):
        """Shadow inherited storage for descriptor bypass tests."""

        __slots__ = "other"

    obj = Derived()
    child = TrackedValue()
    Base.__dict__["_Base__child"].__set__(obj, child)
    Base.__dict__["_sa_internal"].__set__(obj, "skip")
    Derived.__dict__["other"].__set__(obj, 2)

    assert dict(iter_object_fields(obj)) == {
        "_Base__child": child,
        "other": 2,
    }


def test_dictionary_fields_keep_precedence_and_exclusions() -> None:
    """Verify dictionary fields keep precedence and exclusions."""

    class Base:
        """Declare base storage for this regression test."""

        __slots__ = ("child",)

    class Derived(Base):
        """Shadow inherited storage for descriptor bypass tests."""

        pass

    obj = Derived()
    Base.__dict__["child"].__set__(obj, "slot")
    obj.__dict__.update(child="dict", visible=2, _sa_internal=3)

    assert dict(iter_object_fields(obj)) == {"child": "dict", "visible": 2}


def test_shadowed_dictionary_storage_bypasses_property() -> None:
    """Verify shadowed dictionary storage bypasses property.

    Raises:
        AssertionError: The fixture detects property must not run.
    """

    class Base:
        """Declare base storage for this regression test."""

        pass

    def fail(obj: object) -> dict[str, object]:
        """Fail if traversal evaluates the user descriptor under test.

        Args:
            obj: Object whose stored state or fields are accessed.

        Returns:
            The stored value if descriptor access is permitted by this
            fixture.

        Raises:
            AssertionError: The fixture detects property must not run.
        """
        raise AssertionError("property must not run")

    derived = type("Derived", (Base,), {"__dict__": property(fail)})

    obj = derived()
    child = TrackedValue()
    Base.__dict__["__dict__"].__get__(obj)["child"] = child

    assert dict(iter_object_fields(obj)) == {"child": child}


def test_all_underscore_class_name_leaves_private_slot_unmangled() -> None:
    """Verify all underscore class name leaves private slot unmangled."""

    class ___:
        """Declare private slots on an all-underscore class name."""

        __slots__ = ("__child",)

    obj = ___()
    ___.__dict__["__child"].__set__(obj, 1)

    assert dict(iter_object_fields(obj)) == {"__child": 1}
