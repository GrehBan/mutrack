"""Define storage names reserved for mutation tracking bookkeeping."""

from typing import Final

PARENTS: Final = "_tracking_parents"
PARENTS_STORE: Final = "_tracking_parents_store"

STATE: Final = "_state"
STATE_STORE: Final = "_state_store"

CHANGE_SUPPRESS_LEVEL_STORE: Final = "_change_suppress_level_store"
PENDING_CHANGE_STORE: Final = "_pending_change_store"
MAX_DEPTH_LIMIT: Final = "_max_depth_limit"
PARENTS_LOCK_STORE: Final = "_parents_lock_store"
TRACKED_MEMBERS_STORE: Final = "_tracked_members_store"
RUNTIME_STORE: Final = "_tracking_runtime_store"
