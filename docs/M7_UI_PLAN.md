# M7 saved-data interface plan

Status: implemented and checked for the documented M7 scope on October 15, 2026. The original design and starting measurements below are retained as historical requirements. Final evidence and limitations: [M7 acceptance](M7_ACCEPTANCE.md) and [requirement audit](../evidence/m7/final_audit.json).

## Observed problem

Inspection of the running application on port 5056 found 840 rows in the main saved-results list. That list alone occupied 40,320 vertical pixels. The page was 66,339 pixels tall in the inspected 610-pixel-high viewport. M3 repeated 92 runs in a 4,416-pixel list, and M4 repeated 97 in a 4,656-pixel list. Their sweep lists also occupied separate page space. M5 and M6 constrained their history lists to 280 pixels each, but still reserved separate cards for overlapping history and created nested scrolling. Their list contents contained 294 and 253 run rows respectively.

Saved data is dominating layout and repeating across milestone panels. Many cards have similar titles and expose long identifiers without enough useful distinction. Limiting list height addresses one symptom; it does not address duplicated browsing, enormous comparison dropdowns, background full-history loading or the distinction between a benchmark and its child runs.

The M6 record also measured a 112.58-second first acceptance-bundle copy and substantially slower cold history loading than warm requests. Warm listing of 840 cached summaries took approximately 0.09–0.10 seconds. Opening a Library must not require full numerical validation of every saved run.

## Proposed interaction

Use two top-level views: **Experiment** and **Library**. The Library is a dedicated workspace, not another large section appended to the experiment page or a blocking modal. Keep a compact persistent Library button with counts and the active result's short label. Do not reserve space for saved-data lists in experiment controls or milestone sections. Keep experiment controls and results available when returning from the Library.

Conceptual layout:

```text
RangeLab                 Experiment | Library (840 runs, …)

LIBRARY
Search…       Type: All / Runs / Benchmarks / Comparisons
Status…       Model…       Source…          Sort: Newest

Name / scenario       Kind     Date     Outcome     Key settings
Informative noisy     Run      …        Success     joint · Cauchy
Weak-geometry study   Benchmark …       Mixed       2 seeds · 4 variants
  Show runs / attempts…
Gaussian vs rejection Comparison …      Saved       shared observations

25 per page                  Previous · Page … of … · Next

Selected item: summary, provenance, settings, outcome counts
[Open in viewer] [Export] [Use as A] [Use as B]

Compare: A [short label ×]    B [short label ×]    [Compare]
```

This is a structural proposal, not a requirement to copy a wireframe pixel-for-pixel. Match the application's visual language while giving the viewer and scientific controls priority.

### Browse and find

- One cross-version library covers M0–M6 and new M7 runs, all sweep/benchmark families and comparisons. Expose understandable type/model/source/status filters; schema or milestone is an optional advanced filter.
- Default to a compact 25-row page, with at most 50 rows requested per page. Show total and filtered counts, visible range and stable pagination. Render only the current page; no thousands of hidden DOM rows or giant select options.
- Search useful names, scenario, ID and relevant settings. Provide stable sorting by date and sensible scientific fields, with a deterministic ID tie-breaker. Preserve search/filter/sort/page across view changes and refresh.
- Use concise descriptive labels, outcome badges, date and distinguishing model/solver/loss/seed information. Full IDs, full settings and provenance belong in detail/preview, with a copy-ID action. Preserve original labels and identifiers; do not rewrite source artifacts to obtain friendly presentation.
- Show standalone runs and benchmark parents by default. Keep benchmark child runs under their parent with a drill-down through data cell, variant and attempt. Offer an explicit All runs view so every child remains discoverable. Group only through recorded relationships; do not guess duplicates from similar names or delete repeated imports.
- Mixed, failed, nonconverged, interrupted, running and unreadable records must remain discoverable. Never default to hiding failures or substitute zero for missing metrics. Outcome counts must include all recorded attempts and distinguish unattempted cells.

### Inspect, open and compare

Selecting a row previews metadata; it does not solve, regenerate, replace the active scene or silently alter controls. **Open in viewer** explicitly opens the stored result. Benchmark detail retains all-attempt inspection and the ability to select a failed or nonconverged attempt. Detail can be a pane on wide screens and a full-width subview with Back on narrow screens.

Replace huge comparison dropdowns with **Use as A/B** actions and a compact two-slot comparison tray. Selections persist across search, pagination and artifact inspection; each can be removed or replaced explicitly. Show whether selected runs share observations and compatible starts before calling them paired. Preserve existing proper rigid alignment, scale-one/no-reflection rules, missing-estimate handling and all saved comparison exports.

Going to the Library and back must preserve unsaved configuration, selected run/start/ping, scene and comparison cameras, layer toggles, alignment, comparison selections and playback position. Pause active playback while the Experiment view is hidden and return at the same ping in a disclosed paused state. Never silently advance through pings offscreen. Do not destroy/recreate expensive Plotly views or reset their cameras solely for navigation. Persist library navigation state; avoid changing numerical source JSON for UI preferences.

### Responsive and keyboard behavior

The Library fills available workspace height, with one primary results scroller and fixed, reachable search/pagination/actions. On desktop use a compact table and optional detail pane. On narrow screens use prioritized columns or compact cards and a full-width detail view. No full-UUID-driven page overflow, clipped actions or nested scrolling mazes. Maintain visible labels and readable type rather than shrinking everything.

Support keyboard navigation, search focus, labeled filters, explicit row/open controls, visible focus, selection announcements and predictable Back/Escape behavior. Return focus to the Library button or originating row appropriately. Loading, empty search, index rebuilding, unreadable files and failed requests need visible states with safe retry. A changing background job must not reset filters, scroll or selected items.

## Data access and preservation

Use a small, rebuildable metadata index for server-side search/filter/sort/pagination. Choose a justified local implementation; it is a cache of authoritative JSON, not a new source of scientific truth. Update it incrementally after saves/imports/checkpoints and detect external additions/changes/removals. Persist useful artifact relationships and avoid downloading full trajectories, observations or spectra in list responses.

Cold index building may read source metadata, but must not solve, generate observations or repeatedly compute spectral diagnostics for every list request. Avoid repeatedly copying/revalidating all bundled artifacts merely to open the application. Existing bundled copies and evidence must remain untouched. Bound first-page requests and avoid separate full-history fetches from every milestone module. A cold index scan should expose progress, not leave an apparently empty library with no explanation.

Keep strict full-record validation on open, import, compare and export. Clearly distinguish indexed/unchecked summaries from mathematically validated detail. A summary is not a validation certificate. Handle changed or corrupt source files with disclosed stale/pending/error states; document cache-freshness limits. Invalid source data must fail safely at strict boundaries and remain inspectable/exportable as appropriate. Index rebuilding must neither overwrite nor remove source data. Do not add deletion, migration or archival of scientific records as the solution to screen clutter.

## Acceptance for the next agent

1. Preserve and hash every existing observation, run, comparison and acceptance artifact before implementation. M6's 1,195-file manifest is a starting reference, not the full current inventory; the current history has grown.
2. Demonstrate all duplicated inline histories replaced by one Library. Experiment-page height and rendered history-row count must remain independent of 0, current-history and 10,000-record metadata cases. Default 25 rows, maximum page size 50, no full-library DOM or comparison dropdowns. Make test fixtures in isolated temporary directories.
3. Verify search, combinations of filters, stable sorting, pagination, grouped benchmark traversal, selection persistence, preview versus explicit Open, A/B comparison, all-attempt/failure inspection, import and JSON/CSV/PNG exports across retained schemas. Patch solving/generation to fail during offline read workflows.
4. Verify camera, unsaved settings, alignment, layers, selected start/ping, comparison tray and explicit playback pause policy across Library navigation. Reopen/import must never solve or regenerate source observations.
5. Measure cold scan/index/startup, incremental updates, warm paginated queries, payload size, DOM count and browser rendering separately using the real history and an isolated 10,000-record fixture. Target warm first-page metadata responses below 500 ms and a usable warm Library within 1 second on the validation machine; report repeats and actual scope. Fix missed targets or disclose the remaining blocker rather than silently passing it. Do not claim that an index cures all cold-start cost without measurement.
6. Visually inspect desktop 1360×900, the normal compact app viewport and Library at 390×844. New Library workflows must fit and remain keyboard-usable. The existing full application is not mobile-certified; do not expand that claim unless the whole application is actually fixed and checked. Retain screenshots and inspect exported images.
7. Keep M7.1–M7.3 numerical acceptance intact: partial survey knowledge, conditional uncertainty with assumptions and information sources, reproducible studies and explicit limitations. Record requirement-level evidence before checking any M7 item.

The runnable handoff objective is [M7_ORCHESTRATOR_GOAL.md](../M7_ORCHESTRATOR_GOAL.md). This plan authorizes no implementation in its preparation chat.
