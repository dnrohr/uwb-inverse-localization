# Scientific references

These documents explain the numerical models and their assumptions. Use the [user guide](../USER_GUIDE.md) and [input reference](../INPUT_REFERENCE.md) for the current interface and supported configuration fields.

| Document | Scope |
|---|---|
| [Baseline numerical model](BASELINE_NUMERICS.md) | Synchronized planar ranging, coordinate gauges, residuals, initialization and local rank |
| [Experiment format](EXPERIMENT_FORMAT.md) | Native baseline observation records and reproducible synthetic generation |
| [Mathematical review](MATH_REVIEW.md) | Identifiability, reflections, degeneracy and interpretation of local diagnostics |
| [Algebraic initialization](ALGEBRAIC_INITIALIZATION.md) | Measurement-only lifted initialization, validity checks and physical branches |
| [Survey and conditional uncertainty](SURVEY_UNCERTAINTY.md) | World-frame survey constraints/priors, information sources and conditional local intervals |

The baseline references describe their stated model, not every spatial or robust extension. Internal module names and native schema versions identify numerical representations and remain unchanged for saved-data compatibility. Measurement information, prior/survey knowledge and coordinate gauge choices have different meanings. Convergence and full local rank do not establish unique recovery.
