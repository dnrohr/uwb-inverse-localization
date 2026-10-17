# RangeLab — UWB inverse localization

RangeLab is a local application for exploring how UWB range measurements recover a moving tag trajectory and beacon map. Configure a synthetic experiment, fit it under explicit assumptions, and inspect the geometry, residuals and uncertainty in an interactive 3D workspace.

## Quick start

Python 3.12 is the tested environment. In PowerShell, from the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe app.py --port 5057
```

Open [RangeLab](http://127.0.0.1:5057). Keep the server running while using the app. Flask and Plotly run locally; the application requires the Python server.

## Using RangeLab

1. Choose a numerical model in **Experiment** and configure geometry, acquisition, measurement noise, estimator assumptions and numerical settings. Hover over an input or focus it with the keyboard for help.
2. Select **Validate draft**, then **Run experiment** for a single fit or **Run study** for a parameter study.
3. Inspect the selected physical start in the 3D scene and diagnostic tabs. Review all attempts, including failures and nonconvergence.
4. Open **Library** to find saved work, compare two runs, copy a configuration or reuse exact saved observations.
5. Export full JSON records, CSV tables or scene/chart PNGs.

Changes to controls edit the draft; fitting runs only when explicitly requested. Opening a saved result does not replace the draft or rerun the estimator.

## Features

- Planar and spatial geometry with 3–8 beacons, custom paths and tag-height models.
- Sequential ranging, motion profiles, timestamp errors, missing pings and delivery latency.
- Gaussian and robust estimation with simulated NLOS, offsets, correlated noise, quantization and dropout.
- TRF/LM solver comparisons, supported height coordinates, multiple initial starts and paired parameter studies.
- Known maps, partial survey constraints and priors, local observability and conditional uncertainty diagnostics.
- Searchable saved-result Library, shared-scale comparisons and reproducible imports/exports.

Supported combinations vary by model. Convergence, residual fit, geometric accuracy and identifiability are reported separately; full local rank does not establish global uniqueness. Synthetic truth is kept separate from independent fitting inputs. The app works with synthetic experiments; recorded-device ingestion and online estimation are outside its current scope.

## Documentation

- [User guide](docs/USER_GUIDE.md) — setup, workflows, features, examples and troubleshooting.
- [Input reference](docs/INPUT_REFERENCE.md) — every configuration variable, units, limits and defaults.
- [Function and API reference](docs/FUNCTION_REFERENCE.md) — Python interfaces and HTTP routes.
- [Scientific references](docs/science/README.md) — models, coordinate conventions, initialization and uncertainty.
- [Developer guide](docs/DEVELOPMENT.md) — code layout, verification and documentation maintenance.

The app's **User guide** link opens the documentation locally in your browser.

## Project layout

| Directory | Contents |
|---|---|
| `uwb/` | Experiment generation, numerical models, persistence and HTTP adapters |
| `web/` | Browser interface, input help and generated documentation pages |
| `docs/` | User, developer and scientific documentation |
| `tests/` | Automated numerical, service and regression tests |
| `scripts/` | Documentation builds, validation, benchmarks and audits |
| `evidence/` | Retained reference experiments and validation records |
| `runs/` | Local saved experiments, studies and comparisons; Git-ignored |

Back up `runs/` to preserve your saved work. JSON records are authoritative; the Library metadata index can be rebuilt.
