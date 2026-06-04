# Privacy & posture — read-only

This skill **only ever issues HTTP GETs** against the Sigma REST API. It never
calls PUT / POST (except the OAuth token mint) / PATCH / DELETE, so it cannot
create, modify, archive, or delete anything in the customer org.

What it reads:
- `/v2/auth/token` — mints a short-lived bearer token from the client-credential pair.
- `/v2/dataModels` (+ `/{id}/spec`) — the data-model inventory and each model's spec.
- `/v2/workbooks` (+ `/{id}/spec`) — only when `--consumers` is set, to derive
  consuming-workbook counts. Specs are read in memory and reduced to reference
  counts; raw workbook content is not persisted.

What it writes — **locally only**:
- `inventory.json` and `REPORT.md` under the `--out` directory.

Handling the customer's data:
- Put credentials in a local `creds.env` (git-ignored); never commit real client
  secrets. The committed `example/` report is **fully synthetic** (fictional
  "Northwind Trading Co.") — no real customer data is in this repo.
- A real `inventory.json` contains model names, folder paths, and structural counts —
  no warehouse row data, but it **is customer-confidential**. Keep real outputs out of
  any shared/public location and share only with the customer / account team. The
  default `.gitignore` excludes `creds.env` and `assessment-*/` output dirs.
