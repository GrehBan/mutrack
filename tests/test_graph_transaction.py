"""Regression tests for graph transaction."""

from __future__ import annotations

from typing import Any

import pytest

from mutrack.adapters.plain.fields import PLAIN_FIELDS, PlainFieldAccess
from mutrack.tracking.build import build_graph
from mutrack.tracking.graph.linking import transaction
from mutrack.tracking.graph.linking.transaction import LinkTransaction
from mutrack.tracking.parents import get_parents_snapshot
from mutrack.tracking.trackable.protocols import ITrackable
from mutrack.tracking.wrapping import PreparationSession
from tests.graph_support import CONTAINERS, Model, NeutralList
from tests.helpers import InputFailure


def test_session_shares_references_and_defers_all_internal_links() -> None:
    """Verify session shares references and defers all internal links."""
    links = LinkTransaction()
    session = PreparationSession(
        containers=CONTAINERS, max_depth=5, links=links
    )
    child = Model()
    shared = [child]
    first: Any = session.prepare_value(shared)
    second: Any = session.prepare_value({"nested": shared})

    assert first is second["nested"]
    assert not child._tracking_parents
    assert not first._tracking_parents
    links.commit()
    assert child._tracking_parents[first._state] == {0}
    assert first._tracking_parents[second._state] == {"nested"}
    with pytest.raises(RuntimeError):
        session.prepare_value([])
    with pytest.raises(RuntimeError):
        links.commit()


def test_failed_session_cannot_commit_previous_successful_preparations() -> (
    None
):
    """Verify failed session cannot commit previous successful preparations."""
    links = LinkTransaction()
    session = PreparationSession(
        containers=CONTAINERS, max_depth=1, links=links
    )
    child = Model()
    session.prepare_value([child])
    with pytest.raises(ValueError, match="max depth"):
        session.prepare_value([[]])
    with pytest.raises(RuntimeError):
        links.commit()
    assert not child._tracking_parents


def test_transaction_rollback_is_reverse_order_and_keeps_preexisting_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify reverse rollback preserves preexisting keys.

    Args:
        monkeypatch: Pytest fixture that restores temporary method
            replacements.
    """
    parent, child = Model(), Model()
    parent._state.link(child, "existing")
    links = LinkTransaction()
    for key in ("existing", "first", "second", "cycle"):
        links.add(parent, parent if key == "cycle" else child, key)
    seen: list[object] = []
    unlink = transaction.unlink_child

    def record(parent: ITrackable, child: ITrackable, key: Any) -> bool:
        """Record the unlink order exercised by transaction rollback.

        Args:
            parent: Trackable owner of the child reference.
            child: Trackable child participating in the parent
                relationship.
            key: Field name, container key, list index, or None for a
                set member.

        Returns:
            Whether the delegated unlink removed an existing reference.
        """
        seen.append(key)
        return unlink(parent, child, key)

    monkeypatch.setattr(transaction, "unlink_child", record)
    with pytest.raises(ValueError, match="cyclic"):
        links.commit()

    assert seen == ["second", "first"]
    assert child._tracking_parents[parent._state] == {"existing"}


def test_rollback_continues_and_reports_unlink_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify rollback continues and reports unlink failure.

    Args:
        monkeypatch: Pytest fixture that restores temporary method
            replacements.

    Raises:
        InputFailure: The fixture detects unlink second failed.
    """
    parent, child = Model(), Model()
    links = LinkTransaction()
    links.add(parent, child, "first")
    links.add(parent, child, "second")
    links.add(parent, parent, "cycle")
    unlink = transaction.unlink_child

    def fail_once(parent: ITrackable, child: ITrackable, key: Any) -> bool:
        """Inject an unlink failure during rollback.

        Args:
            parent: Trackable owner of the child reference.
            child: Trackable child participating in the parent
                relationship.
            key: Field name, container key, list index, or None for a
                set member.

        Returns:
            Whether the selected reference was removed.

        Raises:
            InputFailure: The fixture detects unlink second failed.
        """
        if key == "second":
            raise InputFailure("unlink second failed")
        return unlink(parent, child, key)

    monkeypatch.setattr(transaction, "unlink_child", fail_once)
    with pytest.raises(ValueError, match="cyclic") as failure:
        links.commit()

    assert child._tracking_parents[parent._state] == {"second"}
    assert any(
        "unlink second failed" in note for note in failure.value.__notes__
    )


def test_field_restore_failure_is_reported_without_stopping_other_restores() -> (
    None
):
    """Verify restoration continues after a field restore failure."""
    first: list[int] = []
    second: list[int] = []
    root = Model(first=first, second=second, cycle=None)
    setattr(root, "cycle", root)

    class FailRestore(PlainFieldAccess):
        """Inject a field restoration failure during rollback."""

        def set_field(
            self, obj: ITrackable, name: str, value: object, /
        ) -> None:
            """Replace stored fields without assignment hooks.

            Args:
                obj: Object whose stored state or fields are accessed.
                name: Stored attribute or declared field name.
                value: Value to read, prepare, store, or compare.

            Raises:
                InputFailure: The fixture detects cannot restore
                    second.
            """
            if name == "second" and value is second:
                raise InputFailure("cannot restore second")
            super().set_field(obj, name, value)

    with pytest.raises(ValueError, match="cyclic") as failure:
        build_graph(root, containers=CONTAINERS, fields=FailRestore())

    assert root.first is first
    assert any(
        "cannot restore second" in note for note in failure.value.__notes__
    )


def test_commit_rejects_cycle_through_preexisting_external_parent() -> None:
    """Verify commit rejects cycle through preexisting external parent."""
    root, external = Model(tags=[], external=None), Model()
    setattr(root, "external", external)
    external._state.link(root, "existing")
    original = root.tags
    before = get_parents_snapshot(root)

    with pytest.raises(ValueError, match="cyclic"):
        build_graph(root, containers=CONTAINERS, fields=PLAIN_FIELDS)

    assert root.tags is original
    assert get_parents_snapshot(root) == before
    assert not external._tracking_parents


def test_deep_model_dfs_is_iterative() -> None:
    """Verify deep model dfs is iterative."""
    root = current = Model()
    for _ in range(1050):
        child = Model()
        setattr(current, "child", child)
        current = child

    build_graph(
        root, containers=CONTAINERS, fields=PLAIN_FIELDS, max_depth=1051
    )
    assert len(current._tracking_parents) == 1


def test_traversal_never_publishes_edges_before_commit() -> None:
    """Verify traversal never publishes edges before commit."""
    child = Model(tags=[])
    root = Model(children=[child], other=Model())

    class CheckDeferred(PlainFieldAccess):
        """Verify that traversal publishes no links before commitment."""

        def iter_fields(self, obj: ITrackable, /) -> Any:
            """Yield available stored model fields.

            Args:
                obj: Object whose stored state or fields are accessed.

            Returns:
                Available field names and their stored values.
            """
            assert not obj._tracking_parents
            return super().iter_fields(obj)

    build_graph(root, containers=CONTAINERS, fields=CheckDeferred())
    assert isinstance(child.tags, NeutralList)
    assert child._tracking_parents[root.children._state] == {0}
