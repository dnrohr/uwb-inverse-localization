# Developer guide

## Source layout

`app.py` creates the Flask application, serves the browser assets and manages the shared background fitting worker. `uwb/` contains synthetic generation, measurement-only estimators, native run/study validation, the Library metadata index and workspace adapters. `web/` contains the shared experiment editor, saved-result renderers, charts, playback and input help.

`tests/` checks numerical and service behavior. `scripts/` contains documentation generation, numerical validation, benchmarking and retained-delivery audits. Native module and script names are retained because tests, schemas and saved records depend on them.

`runs/` holds local saved data and is Git-ignored. `evidence/` holds reference runs and numerical/visual validation records; some application startup fixtures are loaded from it. Keep both directories intact when reorganizing documentation. JSON is authoritative; the Library SQLite cache can be rebuilt.

## Run and verify

Install and start the app using the [README](../README.md). Run the Python suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The browser-independent JavaScript regression checks are:

```powershell
node scripts/check_workspace_download.cjs
node scripts/check_m7_ui_lifecycle.cjs
node scripts/check_m7_ui_regressions.cjs
```

These checks use DOM doubles; verify visible interface changes in a real browser as well. Validation and benchmark scripts can create new evidence and perform many fits. They are not required to start the application or reopen saved results. Delivery audits report the scope of their original records, rather than current product readiness.

## Maintain documentation and input help

Edit [USER_GUIDE.md](USER_GUIDE.md) for workflows. `web/input-help.json` is the shared explanation catalog for configuration paths, interface controls, survey fields and scene layers. `web/help.js` attaches hover/focus explanations and accessible descriptions, including fields added when a form is rebuilt.

Rebuild the input/function references and locally served HTML pages:

```powershell
.\.venv\Scripts\python.exe scripts/build_user_docs.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_user_guide.py -v
```

The builder reads normalized engine defaults and Python signatures without generating observations or fitting. Commit the generated Markdown references and HTML with their sources. Documentation coverage tests check default input explanations, local navigation and read-only delivery.

## Architecture and scientific contracts

See [workspace behavior and API semantics](WORKSPACE.md), the [function/API reference](FUNCTION_REFERENCE.md) and [scientific references](science/README.md). Draft edits, saved-source inspection and fitting are separate operations. Numerical code must keep synthetic truth outside independent fitting inputs and retain every attempt. Supported schemas and strict source validation must remain compatible with saved data.
