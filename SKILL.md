---
name: sigma-data-model-assessment
description: >-
  Audit every Sigma data model in a customer's org against best practices and
  produce a prioritized "what to improve" report — workspace sprawl, promotion-path
  health, duplicate clusters, and per-model findings (missing reusable metrics,
  undeclared relationships behind cross-element Lookups, calc-column bloat, unnamed
  elements, sandbox-source integrity). Read-only, driven by the Sigma REST API.
  Use when a customer wants a health check / governance review of their existing
  Sigma data models, not a migration from another BI tool.
user-invocable: true
---

# Sigma Data Model Assessment

> **STATUS: working inventory (Sigma REST, read-only).** Sibling to
> `tableau-assessment` / `qlik-assessment` etc., but it audits **native Sigma data
> models already in an org** rather than scoping a migration *into* Sigma.
> Validated live against a 340-data-model production org; see `example/` for a
> synthetic sample report (no customer data).

**Read first:**
- `refs/best-practices.md` — the rubric every model is scored against (each signal ties
  to an API-observable fact in the DM spec) and the consumer-count API gotcha.
- `PRIVACY.md` — read-only posture; nothing is ever written to the customer org.

## The key idea
Everything the report flags is derived **only from GETs** against `/v2/dataModels`
(org listing) and `/v2/dataModels/{id}/spec` (each model). The DM spec exposes
exactly the facts that distinguish a healthy model from a problem one: reusable
`metrics`, declared `relationships`, calc-vs-passthrough `columns`, element names,
and source kinds. We score those against `refs/best-practices.md` and rank by a
`concern()` function that puts **source integrity first**, then correctness
(rollup-trap Lookups), then maintainability and discoverability.

## Auth
Client-credential pair (client_id + secret) for the **target customer org**, on that
org's API base (e.g. `https://api.us-a.aws.sigmacomputing.com`). Put them in a
`creds.env` (`SIGMA_CLIENT_ID=…`, `SIGMA_CLIENT_SECRET=…`, `SIGMA_BASE_URL=…`):

```bash
eval "$(scripts/get-token.sh creds.env)"      # sets SIGMA_API_TOKEN + SIGMA_BASE_URL
python3 scripts/dm-assess.py --out assessment-<org> --consumers
```

⚠️ **Always set `SIGMA_BASE_URL` explicitly for the customer org.** If the operator's
shell already exports a `SIGMA_BASE_URL` for a *different* org, the token will be
minted against the wrong region and every call 401s with `Invalid access/refresh
token`. (This is the #1 setup failure.)

## Phases
0. **Auth & probe** — `get-token.sh`; confirm `/v2/whoami` org id; `/v2/dataModels` count.
1. **Org inventory** — page all DMs; bucket by `path` (personal sprawl vs governed
   surface vs sandbox vs write-back); count the promotion path (`1. PRODUCTION`).
2. **Duplicate clustering** — normalized-name clusters (strip `(n)`/`copy`/`UAT`/`v\d`).
3. **Deep per-model analysis** — fetch the spec for every governed-surface DM (cap with
   `--deep-top`); compute metrics/relationships/calc-cols/lookup-risk/empty-names/
   sandbox-refs/dup-formulas per `refs/best-practices.md`.
4. **Consumers (best-effort)** — `--consumers` crawls workbook specs for `dataModelId`
   refs (the `/v2/workbooks?dataModelId=` filter is gated — see rubric). Reports
   coverage; falls back to `latestVersion` as the activity proxy for ranking.
5. **Report** — `REPORT.md`: headline signals, location breakdown, duplicate clusters,
   concern-ranked priority table, ranked recommendations, method & caveats. Full data
   in `inventory.json`.

## Scripts
| Script | Purpose |
|---|---|
| `scripts/get-token.sh` | client_credentials → `SIGMA_API_TOKEN` + `SIGMA_BASE_URL` (retries on the bursty-token 400) |
| `scripts/dm-assess.py` | enumerate + bucket + cluster + deep spec analysis + consumer crawl → `inventory.json` + `REPORT.md` |
| `scripts/render-html.py` | `inventory.json` → polished, customer-facing `report.html` (exec summary + detailed consultative recommendations). `--customer "<name>"` |

Flags: `--out DIR`, `--deep-top N` (0 = all governed), `--deep-min-version N`,
`--consumers`.

## Tuning per org
`PROD_PREFIXES` / `SPRAWL_PREFIXES` in `dm-assess.py` encode what "governed" vs
"personal" looks like by folder path. The defaults match the common
`0. CENTRALIZED…` / `1. PRODUCTION` / `My Documents` convention; adjust for orgs
that name folders differently.

## Open work
- **Consumer counts** are a floor until an admin/elevated token makes
  `/v2/workbooks?dataModelId=` honor the filter (see rubric).
- Per-column lineage into consumer workbooks (which specific Lookup cols are used as
  grouping dims) would turn "0 declared rels — go look" into "these N break".
- Column-similarity (Jaccard) across DMs to find merge candidates beyond name-matching.
