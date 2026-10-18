"""Commit deferred graph edges and roll back only newly created references."""

from __future__ import annotations

from dataclasses import dataclass

from mutrack.tracking.graph.linking.base import link_child, unlink_child
from mutrack.tracking.trackable.protocols import ITrackable
from mutrack.tracking.types import Key


@dataclass(frozen=True, slots=True)
class _PendingLink:
    """Describe one parent-child edge waiting for transactional commitment.

    Attributes:
        parent: Owner of the queued child reference.
        child: Child retained by identity for graph bookkeeping.
        key: Field name or container location of the reference.
    """

    parent: ITrackable
    child: ITrackable
    key: Key


class LinkTransaction:
    """Queue physical edges and commit them without emitting changes.

    Rollback removes only newly created edges, in reverse order.
    Existing edges, including other keys referencing the same child,
    are preserved. A transaction cannot be reused after commit or
    rollback.
    """

    def __init__(self) -> None:
        """Initialize an open transaction with no queued or committed edges."""
        self._pending: list[_PendingLink] = []
        self._created: list[_PendingLink] = []
        self._closed = False

    def ensure_open(self) -> None:
        """Reject operations on a committed or rolled-back transaction.

        Raises:
            RuntimeError: The link transaction has already committed or rolled
                back.
        """
        if self._closed:
            raise RuntimeError("Link transaction is already closed.")

    def add(self, parent: ITrackable, child: ITrackable, key: Key, /) -> None:
        """Queue a parent-child edge without changing the physical graph.

        Args:
            parent: Trackable owner of the child reference.
            child: Trackable child participating in the parent
                relationship.
            key: Field name, container key, list index, or None for a
                set member.
        """
        self.ensure_open()
        self._pending.append(_PendingLink(parent, child, key))

    def commit(self) -> None:
        """Commit queued edges and roll back new edges if any link fails."""
        self.ensure_open()
        try:
            for edge in self._pending:
                if link_child(edge.parent, edge.child, edge.key):
                    self._created.append(edge)
        except BaseException as error:
            self.rollback(error)
            raise
        self._close()

    def rollback(self, error: BaseException | None = None) -> None:
        """Remove committed new edges and report any rollback failures.

        Args:
            error: Original failure to annotate if rollback also fails.

        Raises:
            BaseExceptionGroup: One or more rollback operations fail
                without an original exception.
        """
        failures: list[BaseException] = []
        for edge in reversed(self._created):
            try:
                unlink_child(edge.parent, edge.child, edge.key)
            except BaseException as failure:
                failures.append(failure)
        self._close()
        if failures:
            if error is None:
                raise BaseExceptionGroup(
                    "Graph link rollback failed", failures
                )
            for rollback_error in failures:
                error.add_note(
                    f"Graph link rollback failed: {rollback_error!r}"
                )

    def _close(self) -> None:
        """Close the transaction and release queued object references."""
        self._closed = True
        self._pending.clear()
        self._created.clear()
