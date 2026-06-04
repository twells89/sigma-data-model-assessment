#!/usr/bin/env python3
"""
sigma-data-model-assessment — read-only audit of every Sigma data model in an org.

Enumerates all data models, scores org-level hygiene (workspace sprawl, promotion
path, duplicate clusters), deep-analyzes a priority sample of specs against the
best-practices rubric (refs/best-practices.md), counts consumers per priority DM,
and emits inventory.json + REPORT.md.

Read-only: GETs only. No PUT/POST/PATCH/DELETE is ever issued.

Auth:  eval "$(scripts/get-token.sh creds.env)"   # sets SIGMA_API_TOKEN + SIGMA_BASE_URL
Run:   python3 scripts/dm-assess.py --out assessment-<org>
"""
import argparse, json, os, re, sys, urllib.request, urllib.parse, urllib.error
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

TOKEN = os.environ.get("SIGMA_API_TOKEN", "")
BASE = os.environ.get("SIGMA_BASE_URL", "https://api.us-a.aws.sigmacomputing.com").rstrip("/")

# A "production" / governed surface vs personal sprawl. Tune per org if needed.
PROD_PREFIXES = ("0. CENTRALIZED", "1. PRODUCTION", "FP&A", "2. ", "WRITE BACK")
SPRAWL_PREFIXES = ("My Documents",)

BARE_REF = re.compile(r"^\s*\[[^\]]+\]\s*$")          # passthrough column
AGG_WRAP = re.compile(r"^\s*(Sum|Count|CountDistinct|Avg|Average|Min|Max|Median)\s*\(", re.I)
LOOKUP = re.compile(r"\bLookup\s*\(", re.I)
NORMALIZE_DUP = re.compile(r"""(?ix)
    \s*\(\s*\d+\s*\)\s*$        # trailing (1) (2)
  | \s*-\s*copy\b              # - copy
  | \bcopy\s*$                 # trailing copy
  | \b(uat|qa|dev|test|prod|v\d+|backup|old|new|final|draft)\b
  | [\(\)\[\]]
""")


def api_get(path, **params):
    params.setdefault("skipPermissionCheck", "true")
    qs = urllib.parse.urlencode(params)
    url = f"{BASE}{path}?{qs}" if qs else f"{BASE}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def page_all(path, **params):
    out, page = [], ""
    while True:
        p = dict(params)
        if page:
            p["page"] = page
        d = api_get(path, **p)
        out.extend(d.get("entries", []))
        if not d.get("hasMore"):
            break
        page = d.get("nextPage") or ""
        if not page:
            break
    return out


# ---------- per-spec analysis ----------
def analyze_spec(spec):
    els = [e for pg in spec.get("pages", []) for e in pg.get("elements", [])]
    r = {
        "elements": len(els),
        "empty_named_elements": 0,
        "source_kinds": Counter(),
        "total_columns": 0,
        "calc_columns": 0,
        "passthrough_columns": 0,
        "metrics": 0,
        "relationships": 0,
        "lookup_columns": 0,
        "aggregate_calc_cols": 0,      # calc cols that just wrap Sum()/Count() -> metric candidates
        "dup_formula_clusters": [],
        "typo_shadow_columns": [],     # e.g. 'Defintion' next to 'Definition'
    }
    formula_counts = Counter()
    name_set = set()
    raw_text = json.dumps(spec)
    for e in els:
        nm = (e.get("name") or "").strip()
        if not nm:
            r["empty_named_elements"] += 1
        r["source_kinds"][(e.get("source") or {}).get("kind", "unknown")] += 1
        r["metrics"] += len(e.get("metrics") or [])
        r["relationships"] += len(e.get("relationships") or [])
        for c in e.get("columns", []):
            f = c.get("formula", "") or ""
            r["total_columns"] += 1
            if BARE_REF.match(f):
                r["passthrough_columns"] += 1
                continue
            r["calc_columns"] += 1
            if LOOKUP.search(f):
                r["lookup_columns"] += 1
            if AGG_WRAP.match(f):
                r["aggregate_calc_cols"] += 1
            formula_counts[f] += 1
            cn = (c.get("name") or "").strip().lower()
            if cn:
                name_set.add(cn)
    # duplicate calc-column formulas (defined identically >= 2x)
    for f, n in formula_counts.items():
        if n >= 2 and not BARE_REF.match(f):
            r["dup_formula_clusters"].append({"formula": f[:160], "count": n})
    r["dup_formula_clusters"].sort(key=lambda x: -x["count"])
    r["dup_formula_clusters"] = r["dup_formula_clusters"][:8]
    # cross-element lookups with no declared relationships = the rollup trap
    r["cross_elem_lookup_risk"] = r["lookup_columns"] if r["relationships"] == 0 and r["lookup_columns"] else 0
    # integrity: sandbox/dev source referenced anywhere in spec text
    r["sandbox_refs"] = sorted(set(re.findall(r"[A-Z0-9_]*SANDBOX[A-Z0-9_]*", raw_text)))
    r["source_kinds"] = dict(r["source_kinds"])
    return r


DM_REF = re.compile(r'dataModelId"\s*:\s*"([0-9a-f-]{36})"')


def build_consumer_index():
    """Real consumer counts. NOTE: /v2/workbooks?dataModelId= silently ignores the
    filter on many cred scopes (returns the whole org), so we instead crawl every
    workbook spec and tally the dataModelId references inside it. Tolerant of the
    intermittent 500s the spec endpoint throws. Returns (Counter, coverage dict)."""
    wbs = page_all("/v2/workbooks", limit=200)
    idx, ok, err = Counter(), 0, 0

    def one(w):
        nonlocal ok, err
        try:
            spec = api_get(f"/v2/workbooks/{w['workbookId']}/spec")
            return set(DM_REF.findall(json.dumps(spec)))
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=8) as ex:
        for refs in ex.map(one, wbs):
            if refs is None:
                err += 1
                continue
            ok += 1
            for dm in refs:
                idx[dm] += 1
    return idx, {"workbooks_total": len(wbs), "specs_read": ok, "specs_errored": err,
                 "workbooks_with_dm_ref": sum(1 for _ in idx)}


# ---------- report ----------
def norm_name(n):
    return NORMALIZE_DUP.sub("", (n or "").lower()).strip()


def bucket(path):
    p = path or ""
    if any(p.startswith(x) for x in SPRAWL_PREFIXES):
        return "personal (My Documents)"
    for x in PROD_PREFIXES:
        if p.startswith(x):
            return x.rstrip(". ") or x
    return "other shared"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="assessment-out")
    ap.add_argument("--deep-top", type=int, default=0,
                    help="cap deep analysis to the N highest-version governed DMs (0 = all governed)")
    ap.add_argument("--deep-min-version", type=int, default=2)
    ap.add_argument("--consumers", action="store_true",
                    help="also count consuming workbooks per deep-analyzed DM (slower)")
    args = ap.parse_args()
    if not TOKEN:
        sys.exit("SIGMA_API_TOKEN not set — run: eval \"$(scripts/get-token.sh creds.env)\"")
    os.makedirs(args.out, exist_ok=True)

    print("enumerating data models...", file=sys.stderr)
    dms = page_all("/v2/dataModels", limit=200)
    print(f"  {len(dms)} data models", file=sys.stderr)

    # org-level
    by_bucket = Counter(bucket(d.get("path")) for d in dms)
    # duplicate clusters by normalized name
    clusters = defaultdict(list)
    for d in dms:
        clusters[norm_name(d.get("name"))].append(d)
    dup_clusters = sorted(
        ([{"key": k, "count": len(v), "names": sorted({x.get("name") for x in v}),
           "paths": sorted({x.get("path") for x in v})}
          for k, v in clusters.items() if len(v) >= 2 and k]),
        key=lambda x: -x["count"])
    dup_dm_total = sum(c["count"] for c in dup_clusters)

    # deep sample: the whole governed surface (everything not personal sprawl /
    # sandbox / write-back input tables), highest-churn first. Cap with --deep-top.
    SKIP = ("personal (My Documents)", "WRITE BACK")
    governed = [d for d in dms
                if bucket(d.get("path")) not in SKIP
                and "SANDBOX" not in (d.get("path") or "").upper()
                and (d.get("latestVersion") or 0) >= args.deep_min_version]
    governed.sort(key=lambda d: -(d.get("latestVersion") or 0))
    sample = governed[:args.deep_top] if args.deep_top else governed
    if not sample:
        sample = sorted(dms, key=lambda d: -(d.get("latestVersion") or 0))[:10]

    print(f"deep-analyzing {len(sample)} specs...", file=sys.stderr)
    def fetch(d):
        try:
            spec = api_get(f"/v2/dataModels/{d['dataModelId']}/spec")
            a = analyze_spec(spec)
        except Exception as e:
            a = {"error": str(e)}
        a["_meta"] = {"name": d.get("name"), "path": d.get("path"),
                      "version": d.get("latestVersion"), "id": d["dataModelId"]}
        return a
    with ThreadPoolExecutor(max_workers=8) as ex:
        deep = list(ex.map(fetch, sample))

    coverage = None
    if args.consumers:
        print("building consumer index (crawling workbook specs)...", file=sys.stderr)
        idx, coverage = build_consumer_index()
        for a in deep:
            a["consumers"] = idx.get(a["_meta"]["id"], 0)
        coverage["consumer_counts_reliable"] = (
            coverage["specs_read"] > 0
            and coverage["specs_read"] >= 0.5 * coverage["workbooks_total"]
            and any(a.get("consumers") for a in deep))
        print(f"  read {coverage['specs_read']}/{coverage['workbooks_total']} specs; "
              f"reliable={coverage['consumer_counts_reliable']}", file=sys.stderr)

    inv = {"base": BASE, "generated": datetime.now(timezone.utc).isoformat(),
           "total_dms": len(dms), "by_bucket": dict(by_bucket),
           "duplicate_clusters": dup_clusters, "duplicate_dm_total": dup_dm_total,
           "deep": deep, "all_dms": dms, "consumer_coverage": coverage}
    json.dump(inv, open(os.path.join(args.out, "inventory.json"), "w"), indent=2)

    write_report(args.out, inv)
    print(f"\nReport: {os.path.join(args.out, 'REPORT.md')}", file=sys.stderr)


def write_report(outdir, inv):
    L = []
    w = L.append
    org = inv["base"].split("//")[-1]
    w(f"# Sigma Data Model Assessment\n")
    w(f"_Org API: `{org}` · {inv['total_dms']} data models · generated {inv['generated'][:10]} · **read-only**_\n")

    # headline
    sprawl = inv["by_bucket"].get("personal (My Documents)", 0)
    prod = inv["by_bucket"].get("1. PRODUCTION", inv["by_bucket"].get("1. PRODUCTION".rstrip(". "), 0))
    dups = inv["duplicate_dm_total"]
    deep = [d for d in inv["deep"] if "error" not in d]
    no_metric = sum(1 for d in deep if d.get("metrics", 0) == 0)
    max_calc = max((d.get("calc_columns", 0) for d in deep), default=0)
    max_calc_dm = next((d["_meta"]["name"] for d in deep if d.get("calc_columns", 0) == max_calc), "")
    w("## Headline signals\n")
    w("| Signal | Value | Why it matters |")
    w("|---|---:|---|")
    w(f"| Total data models | {inv['total_dms']} | overall footprint |")
    w(f"| In personal *My Documents* | {sprawl} ({pct(sprawl, inv['total_dms'])}) | personal-workspace sprawl; not governed/promoted |")
    w(f"| In `1. PRODUCTION` | {prod} | health of the promotion path |")
    w(f"| Duplicate-name clusters | {len(inv['duplicate_clusters'])} covering {dups} DMs ({pct(dups, inv['total_dms'])}) | merge/retire candidates |")
    w(f"| Deep-sampled DMs with **0 metrics** | {no_metric} of {len(deep)} | consumers re-implement aggregates downstream |")
    w(f"| Largest calc-column count | {max_calc} on *{max_calc_dm}* | maintenance liability |\n")

    # buckets
    w("## Where the data models live\n")
    w("| Location | DMs |")
    w("|---|---:|")
    for k, v in sorted(inv["by_bucket"].items(), key=lambda x: -x[1]):
        w(f"| {k} | {v} |")
    w("")

    # duplicates
    w("## Duplicate clusters (merge / retire)\n")
    if inv["duplicate_clusters"]:
        w("| Copies | Name(s) | Locations |")
        w("|---:|---|---|")
        for c in inv["duplicate_clusters"][:15]:
            names = "; ".join(list(c["names"])[:3])
            paths = "; ".join(p for p in c["paths"] if p)[:80]
            w(f"| {c['count']} | {names[:70]} | {paths} |")
    else:
        w("_None detected._")
    w("")

    # deep dive
    cov = inv.get("consumer_coverage")
    show_consumers = bool(cov and cov.get("consumer_counts_reliable"))
    w("## Priority data models (deep analysis)\n")
    w("Highest-churn governed data models, by `latestVersion` (edit count proxy).\n")
    chead = " Consumers |" if show_consumers else ""
    w(f"| Data model | v | Elems | Calc cols | Metrics | Rels | Lookup risk | Empty names |{chead} Integrity |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|{'---:|' if show_consumers else ''}---|")
    ranked = sorted([d for d in inv["deep"] if "error" not in d], key=concern, reverse=True)
    errs = [d for d in inv["deep"] if "error" in d]
    shown = ranked[:25]
    for d in shown + errs:
        m = d["_meta"]
        if "error" in d:
            pad = " — |" if show_consumers else ""
            w(f"| {m['name']} | {m['version']} | — | — | — | — | — | — |{pad} err: {d['error'][:30]} |")
            continue
        integ = "🚨 " + ",".join(d["sandbox_refs"]) if d.get("sandbox_refs") else "ok"
        risk = d.get("cross_elem_lookup_risk", 0)
        ccol = f" {d.get('consumers', 0)} |" if show_consumers else ""
        w(f"| {m['name']} | {m['version']} | {d['elements']} | {d['calc_columns']} | "
          f"{d['metrics']} | {d['relationships']} | {risk} | {d['empty_named_elements']} |{ccol} {integ} |")
    if len(ranked) > len(shown):
        w(f"\n_Showing the {len(shown)} highest-concern of {len(ranked)} governed data models analyzed; "
          f"full detail in `inventory.json`._")
    w("")

    # generated recommendations
    w("## Recommendations (ranked)\n")
    recs = build_recs(inv, deep, sprawl, prod, dups, no_metric)
    for i, r in enumerate(recs, 1):
        w(f"{i}. {r}")
    w("")

    w("## Method & caveats\n")
    w("- Read-only. Enumerated via `/v2/dataModels` (paged, `skipPermissionCheck=true`); "
      "specs via `/v2/dataModels/{id}/spec`. No models were modified.\n")
    w("- **Churn proxy:** priority ranking uses `latestVersion` as an edit-count/activity proxy "
      "(a DM at v220 has been edited far more than the v1–3 typical of *My Documents*).\n")
    if cov:
        rel = "usable" if show_consumers else "**not reliable on these creds**"
        w(f"- **Consumer counts ({rel}):** the `dataModelId` filter on `/v2/workbooks` is silently "
          f"ignored (returns the whole org), so consumers are derived by crawling workbook specs for "
          f"`dataModelId` references — read {cov['specs_read']}/{cov['workbooks_total']} specs "
          f"({cov['specs_errored']} returned 5xx). Where workbook specs don't expose source "
          f"`dataModelId`, counts read 0; treat as a floor. An admin/broader-scope token would let "
          f"`/v2/workbooks?dataModelId=` work directly.\n")
    else:
        w("- **Consumer counts:** not computed (run with `--consumers`). Note the "
          "`/v2/workbooks?dataModelId=` filter is gated on many cred scopes.\n")
    w("- Rubric: see `refs/best-practices.md`.\n")

    open(os.path.join(outdir, "REPORT.md"), "w").write("\n".join(L))


def build_recs(inv, deep, sprawl, prod, dups, no_metric):
    """Emitted in priority order: integrity → correctness → governance → hygiene."""
    recs = []

    # 1. integrity (correctness/trust) — fix first
    integ = [d for d in deep if d.get("sandbox_refs")]
    if integ:
        toks = sorted({t for d in integ for t in d["sandbox_refs"]})
        names = ", ".join(f"*{d['_meta']['name']}*" for d in integ[:6])
        tail = ", …" if len(integ) > 6 else ""
        recs.append(f"🚨 **Integrity (fix first):** {len(integ)} governed-surface data models source from "
                    f"{', '.join(toks)} — {names}{tail}. Re-point these to production sources; a sandbox/dev "
                    f"schema behind a centralized model is a trust/correctness risk, not just hygiene.")

    # 2. correctness — undeclared cross-element relationships
    risky = sorted([d for d in deep if d.get("cross_elem_lookup_risk", 0)],
                   key=lambda d: -d["cross_elem_lookup_risk"])
    if risky:
        worst = risky[0]
        more = f" ({len(risky)} DMs affected)" if len(risky) > 1 else ""
        recs.append(f"**Declare relationships** on DMs that rely on cross-element `Lookup()` with zero declared "
                    f"relationships{more} — worst is *{worst['_meta']['name']}* ({worst['cross_elem_lookup_risk']} lookups). "
                    f"As grouping dims these hit the *“Rollup cannot reference more than one external relation”* error.")

    # 3. governance — duplication
    if dups:
        top = inv["duplicate_clusters"][0]
        recs.append(f"**Collapse {len(inv['duplicate_clusters'])} duplicate clusters** (~{dups} DMs). "
                    f"Worst: {top['count']}× *{list(top['names'])[0]}*.")

    # 4. governance — sprawl / promotion path
    if sprawl and sprawl / max(inv["total_dms"], 1) > 0.3:
        recs.append(f"**Tame personal-workspace sprawl** — {sprawl} DMs in *My Documents* "
                    f"({pct(sprawl, inv['total_dms'])}). Establish a promotion path "
                    f"(only {prod} in `1. PRODUCTION` today).")

    # 5. reuse — missing metrics on heavy DMs
    heavy_no_metric = sorted([d for d in deep if d.get("metrics", 0) == 0 and d.get("calc_columns", 0) >= 20],
                             key=lambda d: -d.get("calc_columns", 0))
    if heavy_no_metric:
        names = ", ".join(f"*{d['_meta']['name']}*" for d in heavy_no_metric[:6])
        tmpl = max(deep, key=lambda d: d.get("metrics", 0), default=None)
        ex = f" Use *{tmpl['_meta']['name']}* ({tmpl['metrics']} metrics) as the template." if tmpl and tmpl.get("metrics") else ""
        recs.append(f"**Add reusable metrics** — {no_metric} of {len(deep)} analyzed DMs have zero. Start with the "
                    f"{len(heavy_no_metric)} that carry a heavy calc surface with no metrics: {names}.{ex}")

    # 6. maintainability — duplicate formulas
    dupf = [d for d in deep if d.get("dup_formula_clusters")]
    if dupf:
        worst = max(dupf, key=lambda d: len(d["dup_formula_clusters"]))
        recs.append(f"**Consolidate duplicate calc formulas** inside large DMs — e.g. *{worst['_meta']['name']}* "
                    f"has {len(worst['dup_formula_clusters'])} repeated formula definitions.")

    # 7. discoverability — unnamed elements
    empties = [d for d in deep if d.get("empty_named_elements", 0)]
    if empties:
        worst = max(empties, key=lambda d: d["empty_named_elements"])
        recs.append(f"**Name anonymous elements** — *{worst['_meta']['name']}* has "
                    f"{worst['empty_named_elements']} unnamed elements, so consumers browse blind.")
    return recs


def concern(d):
    """Higher = more in need of attention. Weighted toward correctness/integrity."""
    if "error" in d:
        return 0
    s = 0
    s += 50 if d.get("sandbox_refs") else 0                       # integrity first
    s += 4 * d.get("cross_elem_lookup_risk", 0)                   # rollup-trap lookups
    s += 10 if (d.get("calc_columns", 0) >= 40 and d.get("metrics", 0) == 0) else 0
    s += len(d.get("dup_formula_clusters", []))
    s += 0.2 * d.get("empty_named_elements", 0)
    s += 0.05 * d.get("calc_columns", 0)
    return s


def pct(n, d):
    return f"{(100*n/d):.0f}%" if d else "0%"


if __name__ == "__main__":
    main()
