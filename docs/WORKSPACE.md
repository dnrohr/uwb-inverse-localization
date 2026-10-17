# Unified experiment workspace

The workspace is organized around physical experiments, estimator assumptions and retained evidence. The [user guide](USER_GUIDE.md) describes the interface; this document covers configuration adapters, HTTP APIs and state management.

## Configuration and execution

Workspace configuration version 1 contains `engine`, `physical`, `observation_source`, `assumptions`, `numerical` and `study`. `physical` retains native generation fields except `assumed_std_m`, which belongs to estimator assumptions. Numerical settings include initialization, physical-start perturbation, solver, height parameterization, start seed/count and evaluation budget. Display state and the immutable active source are separate from this editable draft.

The explicit model adapters are:

| Model key | Capability | Native run schema |
|---|---|---|
| `planar` | Synchronized planar baseline | 1.0 |
| `timing` | Timestamp-aware/grouped trajectories | 3.0 |
| `spatial` | Spatial tag/beacon height models | 4.0 |
| `solver` | Solver, height-coordinate and initializer comparisons | 5.0 |
| `robust` | Contamination, robust losses and rejection | 6.0 |
| `survey` | Explicit partial surveyed-world knowledge | 7.0, containing its unchanged schema-6 source experiment |

These adapters normalize and validate through existing native implementations. They do not rewrite objectives, initializers, bounds, frame conventions, strict validators or study pairing algorithms. Unsupported combinations fail explicitly. The survey table edits selected fixed coordinates and independent uncertain covariance blocks; its advanced JSON editor retains exact declarations.

Saved observation reuse requires an exact authoritative Library key, the compatible native experiment schema, and unchanged physical configuration and saved sigmas. New solver/estimator options produce a new run; the source record is never rewritten. There is no automatic schema conversion to make a source fit another model. To change generation settings or sigmas, explicitly select generation. Historical sources without a supported editable representation report an error and remain inspectable/exportable.

Single jobs share the existing background worker and polling lifecycle. Studies delegate to existing native services, preserving their paired observations, physical starts, checkpointing and complete outcomes. Timing studies retain their fixed timestamp-aware/grouped pair. Survey parameter studies are unavailable because no native study engine exists; explicit single survey fits can reuse the same saved observations. Native study limits and restrictions remain enforced.

## HTTP interfaces

| Route | Behavior |
|---|---|
| `GET /api/workspace/capabilities` | Normalized defaults, native schema, supported settings, combination rules and application limits |
| `POST /api/workspace/validate` | Return normalized `configuration`, explicit `engine`, native options and optional normalized native study; no generation/fitting |
| `POST /api/workspace/runs` | Accept a version-1 single-fit draft; return job ID, engine and normalized configuration |
| `POST /api/workspace/studies` | Accept a version-1 parameter-study draft; delegate to the corresponding native checkpointed service |
| `POST /api/workspace/configuration` | Copy a validated saved `run` or Library `key` to a draft; `reuse: true` requires an authoritative key; alternatively accept `native_configuration` |
| `POST /api/workspace/export/csv` | Strictly validate a supplied `run` or Library `key` and export every observation and attempt; a validated comparison `artifact` uses its native table exporter |

The existing `/api/jobs/<id>`, Library and native routes remain available. New single runs store their normalized `workspace_configuration` alongside their native record. Study records retain their native complete configuration and version. Opening, importing, comparing, copying configuration and exporting do not execute a solver or regenerate observations. Uncertainty inspection remains an explicit supported offline calculation, not an implicit browsing cost.

The complete run CSV includes typed source, experiment, estimator-input, observation and attempt rows. `complete_record_json` retains all fields while common measurement fields occupy columns. Native study tables retain their original all-attempt and per-range exports. Run and comparison JSON preserve the validated source structure; ASCII JSON escapes plus an explicit UTF-8 MIME type prevent Unicode objective metadata changing in downloads.

## Inspection and state

One 3D canvas displays either the selected run or the two-run comparison. The selected physical start is shared by plots, metrics, playback and detailed provenance. Comparisons preserve their recorded alignment and proper metric scale; choosing Inspect A/B returns to per-source diagnostics. Results retain native frame and uncertainty disclosures. Unsupported diagnostics show their reason or remain available in the original source JSON; they are not filled with zeros.

The six diagnostic tabs consolidate overview, residuals, geometry/timing, observability/uncertainty, attempts/studies and provenance. Native result renderers remain compatibility adapters; their obsolete forms are removed after initialization, and public form serializers read shared draft state. Opening a source cannot restore a historical form over the draft. Configuration adoption is explicit.

The Library keeps default 25/max 50 metadata rows, grouping, stable sorting, filters and persistent A/B sources. Descriptive search aliases find older source names without rewriting their metadata. Camera, alignment, layers, selected start and draft remain when navigating; playback pauses and stays paused. Narrow screens use a dismissible keyboard-trapped configuration drawer, stacked result views and contained horizontal table scrolling.

## Scientific boundaries and evidence

Convergence, geometric accuracy, residual fit and identifiability remain distinct. Fixed coordinates are constraints; survey/prior information is reported separately from measurements. Conditional local intervals depend on the supported model, saved sigmas, rank and bound assumptions. Full local rank does not establish global uniqueness.

Cold history scans can be expensive; warm cache timings do not imply the same startup performance. Study checkpoints preserve completed entries, not optimizer state. The current application supports synthetic experiments and batch fitting. See the [developer guide](DEVELOPMENT.md) for verification and the [scientific references](science/README.md) for numerical assumptions.
