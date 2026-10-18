# mutrack

`mutrack` tracks mutations inside nested Python object graphs and propagates
change notifications to their containing objects. Its SQLAlchemy integration
lets changes deep inside a mutable attribute mark the owning ORM row dirty.

`TrackedJSON` stores models from any supported field adapter as SQLAlchemy
column values. It initializes assigned and loaded graphs, tracks model field
reassignment as well as container mutation, and persists changes on flush.

The graph layer supports Pydantic models, dataclasses, attrs models, and plain
classes through explicit field adapters. Parent references are weak, shared
children retain their identity, and cycles are rejected.

The current version is `0.1.0`. Use the explicit module imports shown below;
the package root does not re-export the APIs.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [How tracking works](#how-tracking-works)
- [Framework adapters](#framework-adapters)
- [SQLAlchemy integration](#sqlalchemy-integration)
- [Container and wrapping APIs](#container-and-wrapping-apis)
- [Notifications and batching](#notifications-and-batching)
- [Depth, cycles, and failure behavior](#depth-cycles-and-failure-behavior)
- [Limits and troubleshooting](#limits-and-troubleshooting)
- [Extending mutrack](#extending-mutrack)
- [Repository layout and development](#repository-layout-and-development)

## Installation

Python **3.11 or newer** is required. SQLAlchemy and `typing-extensions` are
core dependencies. Pydantic and attrs are optional; dataclasses are part of
the standard library.

From a checkout of this repository:

```sh
python -m pip install -e .
```

Install the framework extras you need:

```sh
python -m pip install -e ".[pydantic]"
python -m pip install -e ".[attrs]"
python -m pip install -e ".[pydantic,attrs]"
```

The Pydantic extra accepts `>=1.10.17,<3`, including the `pydantic.v1`
compatibility namespace. The attrs extra requires `>=23.2`.

For repository development with `uv`, see [Development](#development).

## Quick start

Create and validate your models first, then call `build_graph()`. Every model
that should participate in propagation must implement `ITrackable`; the
`Trackable` mixin supplies the standard implementation.

This complete example uses dataclasses and the bundled SQLAlchemy container
implementations. These containers also work without an ORM session.

```python
from dataclasses import dataclass, field

from mutrack.adapters.dataclasses.fields import DATACLASS_FIELDS
from mutrack.adapters.sqlalchemy.collections.registry import (
    get_sqlalchemy_containers,
)
from mutrack.tracking.build import build_graph
from mutrack.tracking.trackable.trackable import Trackable


@dataclass(eq=False)
class Address(Trackable):
    """Store an address with mutable tags."""

    city: str
    tags: list[str] = field(default_factory=list)


@dataclass(eq=False)
class User(Trackable):
    """Contain an address directly and through a list."""

    name: str
    address: Address
    addresses: list[Address] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


address = Address(city="Warsaw")
user = User(
    name="Ada",
    address=address,
    addresses=[address, address],
    metadata={"history": []},
)
containers = get_sqlalchemy_containers()

build_graph(user, containers=containers, fields=DATACLASS_FIELDS)

assert user.address is user.addresses[0] is user.addresses[1]

user.address.tags.append("new")
assert address.tags == ["new"]
```

Plain list, dictionary, and set fields become their configured Trackable
container subclasses. Scalar fields remain unchanged. Existing Trackable
models are linked directly, including models inside containers.

`eq=False` retains identity equality for these example models. Set members
must also satisfy Python's normal hashability requirements.

## How tracking works

There are two stages:

1. **Initial construction:** `build_graph()` reads model fields, wraps exact
   built-in containers, discovers nested Trackable models, and links the
   resulting graph without emitting change notifications.
2. **Mutation:** Trackable container methods maintain their child links and
   call `changed()`. Notifications propagate through live parents; the
   SQLAlchemy bridge also marks ORM owners dirty.

The quick-start graph contains these edges:

```text
User
├── "address" ────────────> Address
│                          └── "tags" ──> TrackableList
├── "addresses" ─────────> TrackableList
│                          ├── 0 ───────> same Address
│                          └── 1 ───────> same Address
└── "metadata" ──────────> TrackableDict
                           └── "history" ──> TrackableList
```

Appending a tag propagates from the tags list to `Address`, then along its
parent paths to `User`. Multiple locations in the same parent are recorded
as a set of keys. Distinct paths through a shared graph can notify a common
ancestor more than once; [batching](#notifications-and-batching) can coalesce
its notifications.

Children refer to parents through weak state tokens. Linking a child does
not keep its parent alive.

## Framework adapters

Import adapters from their respective `fields` modules:

| Adapter | Import module | Fields inspected |
| --- | --- | --- |
| `PYDANTIC_FIELDS` | `mutrack.adapters.pydantic.fields` | Available declared Pydantic v1/v2 fields, including stored defaults |
| `DATACLASS_FIELDS` | `mutrack.adapters.dataclasses.fields` | Dataclass instance fields, excluding `ClassVar` and `InitVar` |
| `ATTRS_FIELDS` | `mutrack.adapters.attrs.fields` | Declared attrs fields, using storage names rather than constructor aliases |
| `PLAIN_FIELDS` | `mutrack.adapters.plain.fields` | Instance dictionary entries and inherited slots, excluding tracking internals |

Adapters expose fields; they do not make an ordinary object Trackable.
Pydantic extras, computed fields, and private framework metadata are not
included by the Pydantic adapter. Unavailable or unset stored fields are
skipped.

Initial field replacement writes directly to storage, bypassing normal
assignment hooks. It does not rerun Pydantic assignment validation, attrs
converters or validators, or custom `__setattr__` methods. Frozen dataclass,
attrs, and Pydantic instances can therefore contain prepared mutable fields.
Their normal field-assignment restrictions still apply afterward.

### Pydantic

Call the builder after Pydantic finishes validation. This is a complete
example for the installed Pydantic API:

```python
from pydantic import BaseModel, Field

from mutrack.adapters.pydantic.fields import PYDANTIC_FIELDS
from mutrack.adapters.sqlalchemy.collections.registry import (
    get_sqlalchemy_containers,
)
from mutrack.tracking.build import build_graph
from mutrack.tracking.trackable.trackable import Trackable


class Address(Trackable, BaseModel):
    """Validate an address with tracked tags."""

    city: str
    tags: list[str] = Field(default_factory=list)


class User(Trackable, BaseModel):
    """Validate direct and list-contained address models."""

    name: str
    address: Address
    addresses: list[Address]
    metadata: dict[str, object] = Field(default_factory=dict)


address = Address(city="Warsaw")
user = User(name="Ada", address=address, addresses=[address])
build_graph(
    user,
    containers=get_sqlalchemy_containers(),
    fields=PYDANTIC_FIELDS,
)

user.addresses[0].tags.append("listed")
assert user.addresses[0].tags == ["listed"]
```

For the v1 compatibility namespace, import `BaseModel` and `Field` from
`pydantic.v1`; the field adapter stays the same. Model identities are
preserved as they exist **after validation**. Framework copies made before
the build cannot be merged back into shared references.

Serialization needs its own integration. In Pydantic v1, direct `.dict()`
output can include tracking bookkeeping stored in the instance dictionary.
Use an application serializer that selects declared model fields recursively,
and verify its output separately from mutation tracking.

### attrs

The dataclass quick start has an equivalent attrs form:

```python
import attrs

from mutrack.adapters.attrs.fields import ATTRS_FIELDS
from mutrack.adapters.sqlalchemy.collections.registry import (
    get_sqlalchemy_containers,
)
from mutrack.tracking.build import build_graph
from mutrack.tracking.trackable.trackable import Trackable


@attrs.define(eq=False)
class Project(Trackable):
    """Store project tags in an attrs model."""

    tags: list[str] = attrs.field(factory=list)


project = Project()
build_graph(
    project,
    containers=get_sqlalchemy_containers(),
    fields=ATTRS_FIELDS,
)
project.tags.append("tracked")
assert project.tags == ["tracked"]
```

Inherited fields and slots are supported. A private field such as `_tags`
is linked under its storage name, even if its constructor alias is `tags`.

### Plain classes

Plain models can inherit the mixin and use `PLAIN_FIELDS`:

```python
from mutrack.adapters.plain.fields import PLAIN_FIELDS
from mutrack.adapters.sqlalchemy.collections.registry import (
    get_sqlalchemy_containers,
)
from mutrack.tracking.build import build_graph
from mutrack.tracking.trackable.trackable import Trackable


class Settings(Trackable):
    """Store dynamic settings with a nested mutable list."""

    def __init__(self) -> None:
        """Initialize settings before graph construction."""
        self.options: dict[str, list[str]] = {"enabled": []}


settings = Settings()
build_graph(
    settings,
    containers=get_sqlalchemy_containers(),
    fields=PLAIN_FIELDS,
)
settings.options["enabled"].append("search")
assert settings.options == {"enabled": ["search"]}
```

Stored-field traversal avoids evaluating properties. Inherited slots are
read through their declaring descriptors, including slots shadowed by
subclass properties.

### Mixed framework graphs

Use `CompositeFieldAccess` when one graph contains different model kinds:

```python
from mutrack.adapters.attrs.fields import ATTRS_FIELDS
from mutrack.adapters.dataclasses.fields import DATACLASS_FIELDS
from mutrack.adapters.plain.fields import PLAIN_FIELDS
from mutrack.adapters.pydantic.fields import PYDANTIC_FIELDS
from mutrack.tracking.field_access import CompositeFieldAccess

fields = CompositeFieldAccess(
    PYDANTIC_FIELDS, DATACLASS_FIELDS, ATTRS_FIELDS, PLAIN_FIELDS
)
```

Pass `fields` to `build_graph()` with your root and container types. The
first supporting adapter wins, so keep the broad plain adapter last.
Only import optional adapters whose dependencies are installed.

## SQLAlchemy integration

### Model columns with any field adapter

Use `TrackedJSON` to map an entire Trackable model to a JSON document column.
Supply the model class and its field adapter explicitly. Dataclass, attrs,
Pydantic v1/v2, plain, and composite adapters use the same column API.

This complete example tracks both scalar field assignment and nested appends:

```python
from dataclasses import dataclass, field

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from mutrack.adapters.dataclasses.fields import DATACLASS_FIELDS
from mutrack.adapters.sqlalchemy.columns import TrackedJSON
from mutrack.tracking.trackable.trackable import Trackable


@dataclass(eq=False)
class Preferences(Trackable):
    """Store typed preferences as a tracked SQLAlchemy document."""

    language: str = "en"
    tags: list[str] = field(default_factory=list)


class Base(DeclarativeBase):
    """Declare the example database mappings."""

    pass


class Account(Base):
    """Persist a Preferences instance as a JSON column."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    preferences: Mapped[Preferences] = mapped_column(
        TrackedJSON(Preferences, fields=DATACLASS_FIELDS)
    )


engine = create_engine("sqlite://")
Base.metadata.create_all(engine)

with Session(engine) as session:
    account = Account(preferences=Preferences())
    session.add(account)
    session.commit()

    account.preferences.language = "pl"
    account.preferences.tags.append("new")
    assert account in session.dirty
    session.commit()
    session.expire_all()
    assert account.preferences.language == "pl"
    assert account.preferences.tags == ["new"]

engine.dispose()
```

Mapping inputs are accepted at runtime as well as already constructed model
instances. Typed instances preserve their identity and are prepared even when
already of the expected type. Reads reconstruct the model and its graph before
attaching ownership. No manual `build_graph()` or `as_mutable()` call is needed
for `TrackedJSON`; models inherit the framework-neutral `Trackable` mixin.

Choose the adapter for your model:

| Model kind | Column configuration |
| --- | --- |
| Pydantic | `TrackedJSON(Profile, fields=PYDANTIC_FIELDS)` |
| Dataclass | `TrackedJSON(Preferences, fields=DATACLASS_FIELDS)` |
| attrs | `TrackedJSON(Project, fields=ATTRS_FIELDS)` |
| Plain class | `TrackedJSON(Settings, fields=PLAIN_FIELDS)` |
| Mixed nested model kinds | `TrackedJSON(Document, fields=fields)` with a `CompositeFieldAccess` |

Column-enabled graphs support scalar assignment, model and container field
replacement, native field deletion, nested container operations, and models
introduced by later container mutations. Old field values are unlinked after
replacement. Replacing or expiring the ORM column detaches its old root, so
mutations of an externally retained old value cannot dirty that row. Shared
documents notify each live owner independently, without keeping ORM rows alive.

Runtime instrumentation wraps the user model class's native assignment and
deletion methods once. Tracking is enabled per instance, so unconfigured
instances still use normal framework behavior. Pydantic assignment validation
runs when enabled by the model; attrs converters and validators still run.
Frozen models retain their native assignment restrictions while their mutable
fields remain trackable. Rejected assignments restore stored field identities
and Pydantic fields-set metadata; arbitrary side effects inside user validators
are not reversible. Raw dictionary or built-in mutations bypass these hooks.
Deleting a required field can produce a document that its native constructor
cannot reload; preserve your model's required-field invariants.

### Column serialization and configuration

`TrackedJSON` stores declared fields, excluding tracking and ORM bookkeeping.
Its default decoder reconstructs annotated models and `list`, `dict`, `set`,
`frozenset`, tuple, optional, and union values through ordinary constructors.
Common scalar types include enums, dates, times, datetimes, UUIDs, and decimals.
attrs constructor aliases and persisted non-init dataclass/attrs fields are
handled by their adapters. Pydantic decoding uses its native validators.
Plain classes can initialize defaults in a parameterless constructor; remaining
stored fields are then assigned through their normal setters. Field type hints
must be resolvable when typed reconstruction is required.

JSON object keys must be strings. Type annotations are needed to reconstruct
nested model types and containers such as sets; an `Any` or `object` annotation
retains ordinary decoded JSON values. Shared references are preserved within a
live prepared graph, but ordinary JSON storage duplicates shared values, so
identity sharing is not restored after reloading. Cyclic or excessively deep
mapping inputs are rejected before recursive decoding.

| Option | Purpose |
| --- | --- |
| `fields=` | Required field adapter or composite adapter |
| `storage=` | Underlying JSON-compatible SQLAlchemy type; defaults to `JSON()` |
| `max_depth=` | Graph depth limit; defaults to the root model's limit |
| `encode=` | Custom `model -> JSON-compatible data` callback |
| `decode=` | Custom `JSON-compatible data -> model` callback |

For PostgreSQL, pass `storage=JSONB()` from
`sqlalchemy.dialects.postgresql`. Native JSON path expressions remain available
on mapped columns. `None` is supported; mapped nullability and the selected
storage type determine the database's null behavior.

Use custom callbacks for constructors that do not accept stored field names,
schema migrations, polymorphic documents, or specialized value types. The
default encoder reads stored fields; it does not invoke Pydantic field
serializers or include computed fields. A custom v2 encoder can use
`model.model_dump(mode="json")` when those semantics are desired. The default
encoder also avoids the tracking metadata exposed by raw Pydantic v1 `.dict()`.

Mutations mark the entire document column dirty and write its serialized value
on flush. They do not issue per-key JSON database updates or provide conflict
resolution for concurrent writers. Shared live objects require compatible
field adapters and depth settings across their columns. Normal SQLAlchemy
session, refresh, expiration, merge, commit, and rollback behavior still apply.

### Container columns

The bundled implementations extend SQLAlchemy's mutable containers:

| Class | Import module | Intended contents |
| --- | --- | --- |
| `SQLAlchemyTrackableDict` | `mutrack.adapters.sqlalchemy.collections.dict` | Dictionary values, recursively preparing plain containers |
| `SQLAlchemyTrackableList` | `mutrack.adapters.sqlalchemy.collections.list` | List items, with links maintained under current indices |
| `SQLAlchemyTrackableSet` | `mutrack.adapters.sqlalchemy.collections.set` | Hashable members, linked by their actual stored identities |

Use `as_mutable()` on the mapped SQLAlchemy type. A container-root ORM
attribute does not need `build_graph()`; container construction and
SQLAlchemy coercion prepare its nested plain containers.

This complete in-memory example persists an append several levels down:

```python
from typing import Any

from sqlalchemy import JSON, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from mutrack.adapters.sqlalchemy.collections.dict import (
    SQLAlchemyTrackableDict,
)


class Base(DeclarativeBase):
    """Define the example ORM mapping base."""

    pass


class Document(Base):
    """Persist a dictionary with nested mutable contents."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        SQLAlchemyTrackableDict.as_mutable(JSON)
    )


engine = create_engine("sqlite://")
Base.metadata.create_all(engine)

with Session(engine) as session:
    document = Document(payload={"settings": {"tags": []}})
    session.add(document)
    session.commit()

    document.payload["settings"]["tags"].append("new")
    assert document in session.dirty
    session.commit()
    session.expire_all()
    assert document.payload == {"settings": {"tags": ["new"]}}

engine.dispose()
```

The container-only `as_mutable(JSON)` setup requires JSON-compatible values;
it does not serialize arbitrary model objects or sets. Use `TrackedJSON` for
adapter-backed model serialization and reconstruction, or supply an appropriate
storage type and serializer for a custom container-only integration.

`SQLAlchemyTrackable`, in `mutrack.adapters.sqlalchemy.mutable`, supplies the
model-level `Mutable` bridge for custom integrations. Such integrations must
provide their own coercion, serialization, and graph-initialization lifecycle.

## Container and wrapping APIs

`get_sqlalchemy_containers()` returns a cached `ContainerTypes` containing
the three bundled wrapper classes. Passing this registry is an application
choice; the core builder never imports or selects the SQLAlchemy registry.

For lower-level container preparation, import these functions from
`mutrack.tracking.wrapping`:

| API | Behavior |
| --- | --- |
| `prepare_value(value, *, containers, max_depth)` | Wraps exact built-in containers and commits links inside new wrappers; does not attach the result to an external parent |
| `prepare_values(values, *, containers, max_depth)` | Prepares a batch with one shared identity memo, preserving aliases across input values |
| `wrap_value(parent, value, key, *, containers, max_depth=None)` | Prepares a value and links its Trackable result to the supplied parent |
| `PreparationSession(containers=..., max_depth=..., links=...)` | Prepares multiple values while deferring physical links to a caller-owned `LinkTransaction` |

For example, this complete snippet preserves aliases across two inputs:

```python
from mutrack.adapters.sqlalchemy.collections.registry import (
    get_sqlalchemy_containers,
)
from mutrack.tracking.wrapping import prepare_values

shared: list[int] = []
prepared = prepare_values(
    [shared, shared],
    containers=get_sqlalchemy_containers(),
    max_depth=10,
)
assert prepared[0] is prepared[1]
assert prepared[0] is not shared
```

Wrapping converts only **exact** built-in `list`, `dict`, and `set` instances.
Subclasses, tuples, and arbitrary objects are preserved. Dictionary keys are
not wrapped or traversed; values are. Set members are not recursively
wrapped and must remain hashable.

Preparation preserves existing Trackables without inspecting their model
fields. Use `build_graph()` when those fields also need preparation.
`wrap_value()` creates an edge but does not itself assign a model field or
insert a container item; custom mutation code must keep storage and links
consistent.

## Notifications and batching

`Trackable.changed()` propagates a notification through existing parent
links. Override `_emit_change()` when adding an observer, and call
`super()._emit_change()` to retain propagation. The SQLAlchemy containers
already provide the ORM notification bridge.

To coalesce several changes at a particular object, use `batch_changes()`.
With the `user` from the dataclass quick start:

```python
from mutrack.tracking.suppression import batch_changes

with batch_changes(user):
    user.address.tags.append("first")
    user.address.tags.append("second")
```

Nested batches are supported. Pending notifications are emitted when the
outermost batch exits, including when its body raises. Batching changes
notification delivery; it does not roll back storage or create a database
transaction. Batching a root coalesces notifications at that root while
descendant objects continue to receive their own notifications.

## Depth, cycles, and failure behavior

### Graph construction

The builder accepts a supported Trackable **model** root:

```text
build_graph(root, /, *, containers, fields, max_depth=None) -> None
```

Root depth is `1`; each Trackable child adds one level. Scalar leaves do not
add levels. The default limit is `root._max_depth_limit`, which the standard
mixin sets to `100`. A negative limit is invalid, and a limit of zero cannot
accommodate a root. Shared subtrees are checked on every incoming path, so a
shallow first encounter cannot bypass a deeper path's limit.

Pass `max_depth=` to control an individual build. Standalone wrapping APIs
count each supplied value from depth `1` and enforce their wrapping limit
for plain containers; they do not inspect existing Trackable model graphs.

Construction queues all physical edges before committing them. If traversal
or commitment fails, newly committed edges roll back in reverse order and
replaced fields are restored through the field adapter. Existing edges are
preserved. Rollback failures are attached to the original exception as notes
while remaining cleanup actions are attempted.

| Condition | Result |
| --- | --- |
| Root is not Trackable or the adapter does not support it | `TypeError` |
| Root is a list, dictionary, or set | `TypeError`; use a container constructor or wrapping API instead |
| Negative depth, excessive graph depth, or a cycle | `ValueError` |
| Field access, preparation, or a graph hook raises | Original failure propagates after rollback is attempted |

An unchanged graph can be built repeatedly without duplicating its edges.
Initial construction does not call `changed()`.

### Container mutations

Container methods maintain links for the values actually stored. Lists
reconcile shifted indices and resolve stateful slice bounds once. Sets use
the stored representative of an equal member rather than linking an equal
nonmember. Insertion and pop reject indices outside the native signed index
range, matching built-in list behavior.

Failure behavior follows the operation rather than imposing universal
atomicity:

| Operation or failure | Behavior |
| --- | --- |
| Dictionary insertion or set addition fails before storage changes | Newly created parent links and member bookkeeping are rolled back; no change notification |
| Dictionary update fails after successful writes | The successful prefix remains, its links stay consistent, and the public update emits a notification |
| Set difference removes members before its input raises | Removed members are unlinked and the retained change is notified |
| Sorting callbacks mutate the list or raise | Child links are reconciled against the resulting storage, including discarded callback additions |
| Cyclic incoming value is rejected during preparation | Storage is not changed and no change notification is emitted |

Some operations that provably change nothing, such as adding an existing set
member or extending with no values, do not notify. Assignment operations can
still notify when assigned an equal value; notification is not a deep
equality comparison.

## Limits and troubleshooting

**Standalone graph building does not enable assignment tracking.** The
`Trackable` mixin, field adapters, and `build_graph()` alone do not intercept
field reassignment. `TrackedJSON` enables runtime hooks for its model graphs;
`user.address = another_address` is tracked there. Outside such an integration,
custom field mutation code must manage replacement and link removal itself.
Calling `changed()` signals existing parents but does not rebuild edges.

**Rebuilding is for initial preparation, not stale-edge cleanup.** Calling
`build_graph()` after arbitrary field reassignments does not remove old
edges. Do not use it as a substitute for a runtime assignment integration.

**Standalone containers need prepared models.** Containers configured by
`TrackedJSON` automatically prepare and instrument incoming Trackable models.
Ordinary standalone containers treat such models as already prepared. In the
dataclass quick start, build a newly created model before appending it:

```python
new_address = Address(city="Krakow")
build_graph(new_address, containers=containers, fields=DATACLASS_FIELDS)
user.addresses.append(new_address)
new_address.tags.append("new model")
```

**Existing Trackable container storage is left intact during a build.** The
builder discovers Trackable models inside it, but does not recursively wrap
plain containers inserted there through raw built-in methods. Mutate through
the wrapper methods so preparation and bookkeeping run.

**An adapter must recognize nested models.** An unsupported nested Trackable
is linked as an opaque leaf; its fields are not discovered. Ordinary nested
objects that do not implement `ITrackable` also do not propagate changes.
Use a composite adapter for mixed model types.

**Serialization and graph discovery have distinct boundaries.** The default
document codec supports the types described above; custom schemas need codec
callbacks. Tracking discovers the supported mutable containers. Tuple contents
and arbitrary custom collection contents are not recursively discovered for
mutation propagation. Mutating an original plain container retained before
wrapping does not mutate its new wrapper; use the prepared model's value.

**Avoid duplicate initialization hooks.** Models are not built automatically
by their field adapters. Choose a lifecycle point after framework validation
and copying have completed, before the model is used for tracked mutations.

The package exposes Python APIs; no command-line interface is implemented.

## Extending mutrack

### Custom field adapters

Implement the structural `FieldAccess` protocol from
`mutrack.tracking.field_access`:

| Method | Contract |
| --- | --- |
| `supports(obj, /) -> bool` | Reports whether the adapter understands the object's model storage |
| `iter_fields(obj, /) -> Iterable[tuple[str, object]]` | Enumerates available stored field names and values without evaluating computed properties |
| `set_field(obj, name, value, /) -> None` | Replaces stored values without validation, assignment tracking, or change notification; also supports restoring originals |

The core builder has no Pydantic or SQLAlchemy imports. Framework semantics
belong in adapters, container conversion belongs in `tracking.wrapping`, and
physical edge operations belong in `tracking.graph.linking`.

### Custom container types

Supply a `ContainerTypes` instance from `mutrack.tracking.wrapping`. Each
class must subclass its corresponding built-in container, implement
`ITrackable`, and support empty construction without notifications. Wrapping
populates fresh containers through raw built-in operations; runtime mutation
methods must maintain links and send their own notifications.

The bundled mutation-aware implementations are SQLAlchemy adapters. Merely
combining `Trackable` with `list`, `dict`, or `set` does not implement mutation
tracking for that container.

### Structural Trackables

Inheritance from `Trackable` is optional. An implementation can satisfy
`ITrackable` by providing `_max_depth_limit`, `_state`, `_tracking_parents`,
and `changed()`. Use the existing state and parent helpers when implementing
these contracts so weak references and cycle checks are retained.
`is_trackable()` checks support per instance, including implementations
whose required members are installed in instance storage.

## Repository layout and development

```text
src/mutrack/
├── adapters/
│   ├── attrs/            Field access and framework attribute rules
│   ├── dataclasses/      Field access and framework attribute rules
│   ├── plain/            Stored fields on ordinary classes
│   ├── pydantic/         Pydantic v1/v2 field access
│   └── sqlalchemy/       ORM bridge and mutation-aware containers
├── internal/             Storage names, raw object access, and sentinels
├── introspection/        Field discovery and internal-field exclusions
└── tracking/             Build, wrapping, state, links, and notifications
tests/                    Graph, adapter, mutation, and ORM regressions
```

### Development

The repository's `.python-version` selects Python `3.15`. Install the dev
dependencies and lint group with:

```sh
uv sync --group lint
```

| Command | Purpose |
| --- | --- |
| `uv run pytest -q` | Run the complete regression suite |
| `uv run --group lint ruff check .` | Check lint rules and import order |
| `uv run --group lint ruff format --check .` | Verify formatting |
| `uv run --group lint mypy --strict --no-incremental` | Run strict source type checks |
| `uv run --group lint ruff check --select D --config "lint.pydocstyle.convention='google'" src tests` | Check Google-style docstrings |
| `uv build` | Build the wheel and source distribution |

For an additional Pyright check on Windows:

```sh
uvx --from pyright pyright --pythonpath .venv/Scripts/python.exe src tests
```

On Unix-like systems, use `.venv/bin/python` for `--pythonpath`.

The test suite covers shared references, duplicate locations, cycle and depth
rejection, hook-free field replacement, rollback, stateful index conversion,
exceptional hash behavior, and SQLAlchemy dirty tracking and persistence.
There is no configured coverage threshold.

Run the native Pydantic v1 compatibility suite in an isolated environment
without replacing the normal v2 development dependency:

```sh
uv run --isolated --no-project --python 3.15 --with-editable . --with "pydantic>=1.10.17,<2" --with "attrs==23.2.0" --with "pytest>=9.1.1" python -m pytest -q
```

This run skips the computed-field test that applies only to Pydantic v2.
The normal suite also exercises the `pydantic.v1` compatibility namespace.

Follow [AGENTS.md](AGENTS.md) for contributor conventions. Keep new Python
code fully annotated and documented with Google-style docstrings. Add
regressions for behavior changes, and report the relevant checks in pull
requests.
