# Sigma Data Model Assessment

A **read-only** audit of every data model in a [Sigma](https://www.sigmacomputing.com/)
organization, scored against data-model best practices, that produces a prioritized
**"what to improve" report** — as polished customer-facing HTML and as Markdown.

It answers: *"We have hundreds of Sigma data models — which ones are risky, which are
redundant, and what should we fix first?"*

> This is an [agent skill](https://docs.claude.com/en/docs/claude-code) (works as a
> Claude Code / Agent skill via `SKILL.md`) **and** a standalone CLI — the scripts run
> fine on their own with Python 3 (standard library only) and `curl`.

<p align="center"><i>Sample report (synthetic data) — see <a href="example/sample-report.html"><code>example/sample-report.html</code></a></i></p>

---

## What it checks

Everything is derived **only from HTTP GETs** against the Sigma REST API — the tool
never creates, edits, or deletes anything in your org.

| Area | Signal | Why it matters |
|---|---|---|
| **Integrity** | Governed models sourcing from a `*SANDBOX*`/dev schema | Production dashboards trusting non-production data — a correctness risk, ranked first |
| **Correctness** | Cross-element `Lookup()` with **0 declared relationships** | Breaks charts at *view time* with *"Rollup cannot reference more than one external relation"* — no build-time warning |
| **Governance** | Workspace sprawl (personal vs. governed) & promotion-path health | Shared models stuck in personal spaces aren't owned, discoverable, or trustworthy |
| **Governance** | Duplicate clusters (`X DM`, `X DM (1)`, `X DM Test`, UAT/backup) | Split usage and drifting definitions |
| **Reusability** | Models with **0 reusable metrics** but a heavy calc surface | Every dashboard re-implements the same aggregates → KPIs drift |
| **Maintainability** | The same formula defined many times in one model | Change-in-many-places risk |
| **Discoverability** | Unnamed elements / typo columns shadowing real ones | Consumers rebuild instead of reuse |

Findings are ranked by a `concern()` score that puts **integrity → correctness →
governance → maintainability → discoverability**. The full rubric, with how each
signal maps to a fact in the data-model spec, is in
[`refs/best-practices.md`](refs/best-practices.md).

## Quick start

**Requirements:** Python 3.8+ (standard library only) and `curl`. No `pip install`.

1. Create a Sigma **API client** (client ID + secret) in *Administration → Developer
   Access* for the org you want to assess. A read/viewer scope is enough.

2. Copy the creds template and fill it in:
   ```bash
   cp creds.env.example creds.env      # creds.env is git-ignored
   # edit creds.env:
   #   SIGMA_CLIENT_ID=...
   #   SIGMA_CLIENT_SECRET=...
   #   SIGMA_BASE_URL=https://api.<region>.aws.sigmacomputing.com
   ```
   > ⚠️ **Always set `SIGMA_BASE_URL` to the assessed org's region explicitly.** If your
   > shell already exports a `SIGMA_BASE_URL` for a different org, the token is minted
   > against the wrong region and every call returns `401 Invalid access/refresh token`.
   > (Find your base in the Sigma API docs for your cloud/region.)

3. Run the assessment:
   ```bash
   eval "$(scripts/get-token.sh creds.env)"        # → SIGMA_API_TOKEN + SIGMA_BASE_URL
   python3 scripts/dm-assess.py --out assessment-acme
   python3 scripts/render-html.py \
       --inv assessment-acme/inventory.json \
       --out assessment-acme/report.html \
       --customer "Acme Corp"
   open assessment-acme/report.html      # macOS; use xdg-open on Linux
   ```

Outputs land in `assessment-acme/`:
- `inventory.json` — full structured results (every model + per-model deep analysis)
- `REPORT.md` — Markdown report
- `report.html` — polished, customer-facing report (exec summary + detailed recommendations)

## How it works

```
get-token.sh ──► SIGMA_API_TOKEN          (client_credentials grant, retries the bursty-token 400)
dm-assess.py ──► /v2/dataModels           enumerate + bucket by folder + duplicate clusters
             ──► /v2/dataModels/{id}/spec  deep structural analysis of the governed surface
             ──► /v2/workbooks (+contents) optional --consumers (best-effort, see note)
             ──► inventory.json + REPORT.md
render-html.py ─► report.html             customer-facing HTML from inventory.json
```

### The data-model spec, briefly
Each model's spec (`/v2/dataModels/{id}/spec`) is `pages[].elements[]`. Per element:
`source.kind` (`warehouse-table` | `table` | `data-model` | `union` | `sql`),
`columns[]` (**every column is a `formula`** — a bare `[ref]` is passthrough, an
expression is a calc), `metrics[]` (reusable aggregates), and `relationships[]`
(declared joins). Healthy models have metrics and relationships; problem models have
zero of both. See [`refs/best-practices.md`](refs/best-practices.md).

## Scripts

| Script | Purpose |
|---|---|
| `scripts/get-token.sh` | client_credentials → `SIGMA_API_TOKEN` + `SIGMA_BASE_URL` (with retry/backoff) |
| `scripts/dm-assess.py` | enumerate + bucket + cluster + deep spec analysis (+ optional consumer crawl) → `inventory.json` + `REPORT.md` |
| `scripts/render-html.py` | `inventory.json` → polished `report.html` with detailed recommendations |
| `example/make-sample.py` | regenerate the synthetic `example/` fixture |

**Useful flags** (`dm-assess.py`): `--out DIR`, `--deep-top N` (0 = analyze the whole
governed surface), `--deep-min-version N`, `--consumers`.

### Tuning per org
`PROD_PREFIXES` / `SPRAWL_PREFIXES` near the top of `dm-assess.py` define what
"governed" vs. "personal" looks like by folder path. Defaults match the common
`0. CENTRALIZED…` / `1. PRODUCTION` / `My Documents` convention — adjust for orgs that
name folders differently.

## Consumer counts — a known API caveat
The most reliable "which models are actually used" ranking would come from
`/v2/workbooks?dataModelId=<id>`, but **that filter is silently ignored on standard
client-credential scopes** (returns the whole org). `--consumers` falls back to
crawling workbook specs for `dataModelId` references; that endpoint is rate-limited and
many specs don't expose the source model, so counts are a **floor**. Until an
admin/elevated token makes the direct filter work, ranking uses each model's edit count
(`latestVersion`) as an activity proxy. The report states which mode was used.

## Privacy & safety
Read-only by construction (only GETs, plus the OAuth token mint). See
[`PRIVACY.md`](PRIVACY.md). The committed [`example/`](example/) report is **fully
synthetic** — no real customer data is in this repo. Real `inventory.json`/report
outputs are customer-confidential; the default `.gitignore` keeps `creds.env` and
`assessment-*/` out of git.

## License
MIT — see [`LICENSE`](LICENSE).
