# Sigma Data Model Assessment

_Org API: `api.example.aws.sigmacomputing.com` · 122 data models · generated 2026-06-04 · **read-only**_

## Headline signals

| Signal | Value | Why it matters |
|---|---:|---|
| Total data models | 122 | overall footprint |
| In personal *My Documents* | 78 (64%) | personal-workspace sprawl; not governed/promoted |
| In `1. PRODUCTION` | 1 | health of the promotion path |
| Duplicate-name clusters | 4 covering 12 DMs (10%) | merge/retire candidates |
| Deep-sampled DMs with **0 metrics** | 5 of 10 | consumers re-implement aggregates downstream |
| Largest calc-column count | 190 on *Sales Mart DM* | maintenance liability |

## Where the data models live

| Location | DMs |
|---|---:|
| personal (My Documents) | 78 |
| 0. CENTRALIZED | 22 |
| other shared | 12 |
| FP&A | 9 |
| 1. PRODUCTION | 1 |

## Duplicate clusters (merge / retire)

| Copies | Name(s) | Locations |
|---:|---|---|
| 4 | Sales Mart DM; Sales Mart DM (1); Sales Mart DM Test | 0. CENTRALIZED/Sales; My Documents |
| 3 | Customer 360 DM; Customer 360 DM (1) | 0. CENTRALIZED/CRM; My Documents |
| 3 | Finance Targets DM; Finance Targets DM UAT | FP&A/Models; My Documents/Archived Users/j.doe |
| 2 | Returns DM; Returns DM (1) | 0. CENTRALIZED/Ops; My Documents |

## Priority data models (deep analysis)

Highest-churn governed data models, by `latestVersion` (edit count proxy).

| Data model | v | Elems | Calc cols | Metrics | Rels | Lookup risk | Empty names | Integrity |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| Sales Mart DM | 180 | 24 | 190 | 0 | 0 | 18 | 9 | ok |
| Legacy Orders DM | 60 | 27 | 50 | 0 | 6 | 0 | 14 | 🚨 DEV_SANDBOX |
| Inventory Snapshot DM | 40 | 7 | 30 | 0 | 0 | 2 | 2 | 🚨 DEV_SANDBOX |
| Returns DM | 22 | 10 | 25 | 0 | 0 | 0 | 6 | 🚨 DEV_SANDBOX |
| Customer 360 DM | 80 | 25 | 28 | 11 | 0 | 12 | 10 | ok |
| Revenue Gold DM | 210 | 58 | 100 | 64 | 27 | 0 | 48 | ok |
| Finance Targets DM | 70 | 18 | 70 | 0 | 0 | 0 | 3 | ok |
| Marketing Spend DM | 55 | 20 | 44 | 1 | 0 | 2 | 1 | ok |
| Pricing DM | 18 | 8 | 21 | 2 | 0 | 1 | 2 | ok |
| Web Analytics DM | 33 | 12 | 30 | 8 | 4 | 0 | 1 | ok |

## Recommendations (ranked)

1. 🚨 **Integrity (fix first):** 3 governed-surface data models source from DEV_SANDBOX — *Legacy Orders DM*, *Inventory Snapshot DM*, *Returns DM*. Re-point these to production sources; a sandbox/dev schema behind a centralized model is a trust/correctness risk, not just hygiene.
2. **Declare relationships** on DMs that rely on cross-element `Lookup()` with zero declared relationships (5 DMs affected) — worst is *Sales Mart DM* (18 lookups). As grouping dims these hit the *“Rollup cannot reference more than one external relation”* error.
3. **Collapse 4 duplicate clusters** (~12 DMs). Worst: 4× *Sales Mart DM*.
4. **Tame personal-workspace sprawl** — 78 DMs in *My Documents* (64%). Establish a promotion path (only 1 in `1. PRODUCTION` today).
5. **Add reusable metrics** — 5 of 10 analyzed DMs have zero. Start with the 5 that carry a heavy calc surface with no metrics: *Sales Mart DM*, *Finance Targets DM*, *Legacy Orders DM*, *Inventory Snapshot DM*, *Returns DM*. Use *Revenue Gold DM* (64 metrics) as the template.
6. **Consolidate duplicate calc formulas** inside large DMs — e.g. *Sales Mart DM* has 3 repeated formula definitions.
7. **Name anonymous elements** — *Revenue Gold DM* has 48 unnamed elements, so consumers browse blind.

## Method & caveats

- Read-only. Enumerated via `/v2/dataModels` (paged, `skipPermissionCheck=true`); specs via `/v2/dataModels/{id}/spec`. No models were modified.

- **Churn proxy:** priority ranking uses `latestVersion` as an edit-count/activity proxy (a DM at v220 has been edited far more than the v1–3 typical of *My Documents*).

- **Consumer counts (**not reliable on these creds**):** the `dataModelId` filter on `/v2/workbooks` is silently ignored (returns the whole org), so consumers are derived by crawling workbook specs for `dataModelId` references — read 0/0 specs (0 returned 5xx). Where workbook specs don't expose source `dataModelId`, counts read 0; treat as a floor. An admin/broader-scope token would let `/v2/workbooks?dataModelId=` work directly.

- Rubric: see `refs/best-practices.md`.
