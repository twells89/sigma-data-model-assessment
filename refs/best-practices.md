# Sigma Data Model best-practices rubric

What the assessment scores each data model against. Each signal maps to a concrete
API-observable fact in the DM spec (`/v2/dataModels/{id}/spec`) or the org listing
(`/v2/dataModels`). "Good" examples are drawn from healthy production models
(e.g. a DM with reusable metrics + declared relationships); "anti-pattern" examples
are the ones the audit flags.

## Spec shape (so the signals make sense)
- `spec.pages[].elements[]` — each element is a node on the DM canvas.
- `element.source.kind` — `warehouse-table` | `table` (ref to another element) |
  `data-model` (imports another DM's element) | `union` | `sql`.
- `element.columns[]` — **every column is a `formula`.**
  - *Passthrough* column: formula is a bare reference, e.g. `[Orders/Amount]`.
  - *Calc* column: formula is an expression, e.g. `[Gross Revenue] + [Dilution]`.
  - `column.name` present ⇒ renamed/derived (surfaced to consumers).
- `element.metrics[]` — **reusable aggregates** (the good stuff). `Sum(...)`, ratios, etc.
- `element.relationships[]` — **declared joins** (`targetElementId` + key pairs).

## The rubric

### 1. Governance / promotion path  *(org-level)*
- **Good:** most DMs live on a curated, named surface (`0. CENTRALIZED…`,
  `1. PRODUCTION`, a team folder); a real promotion path is used.
- **Anti-pattern:** majority in personal `My Documents`; `1. PRODUCTION` near-empty.
- **Signal:** `path` bucket distribution; count in `1. PRODUCTION`.

### 2. Duplication  *(org-level)*
- **Good:** one canonical DM per domain; copies are short-lived.
- **Anti-pattern:** `X DM`, `X DM (1)`, `X DM Test`, UAT/backup copies side-by-side.
- **Signal:** normalized-name clustering (strip `(n)`, `copy`, `UAT/QA/dev/test/v\d`).
  Clusters of ≥2 are merge/retire candidates.

### 3. Reusable metrics  *(per-DM)*
- **Good:** business aggregates defined once as `element.metrics`, so every consumer
  workbook references the same definition.
- **Anti-pattern:** **0 metrics** on a heavily-used DM ⇒ each consumer re-implements
  `Sum(...)` downstream; definitions drift. Aggregate-shaped calc columns
  (`Sum([X])` living as a *column*, not a metric) are metric candidates.
- **Signal:** `metrics` count; `aggregate_calc_cols` (Sum/Count/Avg wrappers in columns).

### 4. Declared relationships vs. cross-element Lookup  *(per-DM — correctness)*
- **Good:** elements that need to join declare `relationships`; the query planner
  resolves the join at query time.
- **Anti-pattern:** cross-element `Lookup()` columns with **0 declared relationships**.
  Fine for scalar measures, but when such a column is used as a *grouping dimension*
  in a chart, Sigma can resolve only one external relation per query and the chart
  renders the literal error string **"Rollup cannot reference more than one external
  relation"** — with no POST/verify-time error. (See memory
  `feedback_sigma_rollup_external_relation`.)
- **Signal:** `lookup_columns` when `relationships == 0` ⇒ `cross_elem_lookup_risk`.

### 5. Calc-column bloat  *(per-DM — maintainability)*
- **Good:** lean elements; shared logic centralized.
- **Anti-pattern:** very high calc-column counts (e.g. 150+), especially with 0 metrics;
  the same formula defined many times across elements.
- **Signal:** `calc_columns`; `dup_formula_clusters` (identical formula ≥2×).

### 6. Discoverability  *(per-DM)*
- **Good:** every element has a meaningful name.
- **Anti-pattern:** imported/sub-model elements left unnamed ⇒ consumers can't tell
  `Revenue - Air` from `Revenue - Hotel` without clicking in. Typo columns shadowing
  the real one (`Defintion` vs `Definition`).
- **Signal:** `empty_named_elements`; `typo_shadow_columns`.

### 7. Source integrity  *(per-DM — highest priority)*
- **Good:** governed DMs source only from governed/production warehouse objects.
- **Anti-pattern:** a DM on the centralized/production surface that sources from a
  `*SANDBOX*` / dev schema. This is a *correctness/trust* issue, not hygiene — it
  ranks above everything else.
- **Signal:** `sandbox_refs` (any `*SANDBOX*` token in the spec) on a governed-surface DM.

## Concern scoring (how the report sorts "fix first")
Integrity (sandbox source) dominates, then rollup-trap lookups, then big-calc-no-metrics,
then duplicate formulas, then unnamed elements and raw calc-column volume. See
`concern()` in `scripts/dm-assess.py`.

## Consumer counts — known API gotcha
`/v2/workbooks?dataModelId=<id>` **silently ignores the filter** on standard
client-credential scopes (returns the whole org). Real consumer counts therefore come
from crawling each workbook for `dataModelId` references — but `/v2/workbooks/{id}?includeContents=true`
is rate-limited / intermittently 5xx and many specs don't expose source `dataModelId`,
so counts are a **floor**. An admin/elevated token makes the direct filter work.
Until then, rank by `latestVersion` (edit-count proxy).
