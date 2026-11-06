---
paths:
  - "tests/resources/**"
  - "tests/resource_corpus.py"
  - "tests/resource_models.py"
  - "tests/test_resource_*.py"
  - "tests/test_system_resources.py"
  - "tests/test_spec_schema.py"
  - "yellowdog_cli/utils/specs/sdk_models.py"
  - "yellowdog_cli/utils/resource_creation.py"
---

## Resource Specification Test Corpus

`tests/resources/` is the single source of resource specifications used by the resource-definition tests (`test_resource_specs.py`, `test_resource_property_coverage.py`, `test_system_resources.py`, `test_spec_schema.py`, through `tests/resource_corpus.py`) — one Jsonnet file per resource type, each with a minimal variant (only required properties) and a maximal one (every settable property), loaded through the CLI's own loader rather than duplicated as separate fixtures. See `tests/resources/README.md` for the minimal/maximal convention and how to add a new resource type.

`tests/resource_models.py` is a write-side coverage gate: it introspects the SDK's own dataclasses for every model the corpus's resource types build (via `resource_creation.py`'s `_get_model_object`) and fails, naming the property, when a settable property is set by no specification at all. A property can only be excluded from the gate by a registry entry (`SERVER_ASSIGNED_COVERAGE`, `NOT_SETTABLE`, `NOT_TESTED`) carrying a stated reason. Those registries, `MODEL_FOR_RESOURCE` and `settable_properties()` live in `yellowdog_cli/utils/specs/sdk_models.py`, shared with the specification schemas, and `resource_models.py` re-exports them under the same names (the same objects, so a test mutating one changes what the gate reads); `build_models()`, `comparable()` and the nested-model walk stay in the tests, being the gate's alone. An exclusion is never inferred from the dataclass's own `field.init`, since the SDK structures an `init=False` field from a specification exactly like any other. A live read gate in `test_system_resources.py` then demands every property excluded as platform-assigned either actually come back from a real `yd-show` at least once, or carry a recorded reason why this suite cannot make it come back (most of the waived ones belong to a compute source that never provisions a real instance, so it has no status, no instance summary and no exhaustion to report); an exclusion the platform has started honouring is reported as stale, so a waiver cannot outlive its reason. Consequently, closing a coverage gap the SDK opens (a new property on an existing model) is an edit to one `.jsonnet` file.
