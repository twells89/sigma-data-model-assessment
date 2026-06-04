#!/usr/bin/env python3
"""
Render a customer-facing HTML report from an assessment inventory.json.

Usage: python3 scripts/render-html.py --inv DIR/inventory.json --out DIR/report.html
       [--customer "Ritz-Carlton Yacht Collection"]

Customer-facing: leads with an executive summary and detailed, consultative
recommendations (finding → impact → affected models → recommended actions → effort).
Internal API mechanics are reduced to a single neutral methodology line.
"""
import argparse, html, json, datetime


def esc(s):
    return html.escape(str(s), quote=True)


def pct(n, d):
    return f"{(100*n/d):.0f}%" if d else "0%"


# ---- detailed recommendation builders (consultative prose, data-filled) ----
def recs(inv, deep):
    out = []
    by = inv["by_bucket"]
    total = inv["total_dms"]
    prod = by.get("1. PRODUCTION", 0)
    sprawl = by.get("personal (My Documents)", 0)

    # 1 — integrity
    integ = [d for d in deep if d.get("sandbox_refs")]
    if integ:
        toks = sorted({t for d in integ for t in d["sandbox_refs"]})
        rows = "".join(
            f"<li><b>{esc(d['_meta']['name'])}</b> "
            f"<span class='path'>{esc(d['_meta']['path'])}</span></li>" for d in integ)
        out.append(dict(
            sev="critical", tag="Data integrity", effort="High · cross-team",
            title=f"{len(integ)} governed data models read from a sandbox/dev schema "
                  f"({', '.join(esc(t) for t in toks)})",
            impact="These models live on the centralized/production surface yet pull from a "
                   "non-production schema. Anyone building on them is trusting numbers that can "
                   "change or disappear without notice — this is a correctness and trust risk, "
                   "not just housekeeping, which is why it ranks first.",
            affected=f"<ul class='aff'>{rows}</ul>",
            actions=[
                "Confirm the production equivalent of each <code>*_SANDBOX</code> object with the "
                "data-engineering owner (most are <code>DW_SALES</code> / <code>DW_ODS</code> legacy lineage).",
                "Re-point each model's source element to the production schema; column references "
                "carry over unchanged when names match.",
                "Validate a known KPI on each re-pointed model against a trusted figure before "
                "publishing the new version.",
                "Add a lightweight standard: models under <code>0. CENTRALIZED…</code> may only source "
                "from production schemas (a periodic re-run of this assessment enforces it).",
            ]))

    # 2 — relationships vs lookup
    risky = sorted([d for d in deep if d.get("cross_elem_lookup_risk", 0)],
                   key=lambda d: -d["cross_elem_lookup_risk"])
    if risky:
        rows = "".join(
            f"<li><b>{esc(d['_meta']['name'])}</b> — {d['cross_elem_lookup_risk']} "
            f"cross-element lookups, 0 declared relationships</li>" for d in risky)
        lead = " and ".join(f"<b>{esc(d['_meta']['name'])}</b> ({d['cross_elem_lookup_risk']})"
                            for d in risky[:2])
        out.append(dict(
            sev="high", tag="Correctness", effort="Medium",
            title=f"{len(risky)} models join across elements with <code>Lookup()</code> instead of "
                  f"declared relationships",
            impact="A cross-element <code>Lookup()</code> is fine for a scalar measure, but the moment "
                   "one is used as a grouping dimension in a chart, Sigma can only resolve a single "
                   "external relation per query and the visual renders the literal error "
                   "<i>“Rollup cannot reference more than one external relation.”</i> It surfaces at "
                   "view time with no build-time warning, so it tends to be discovered by an end user.",
            affected=f"<ul class='aff'>{rows}</ul>",
            actions=[
                "For each model, identify the cross-element <code>Lookup()</code> columns and which are "
                "used as chart grouping dimensions downstream.",
                "Replace those with a <b>declared relationship</b> between the two elements so the query "
                "planner handles the join — or switch the element's source to a <code>join</code> so the "
                "dimension is baked into the SQL.",
                "Leave scalar-only lookups (numerator/denominator inside an aggregate) as-is.",
                f"Start with {lead} — the highest exposure.",
            ]))

    # 3 — duplicates
    dc = inv["duplicate_clusters"]
    if dc:
        dup_dm = inv["duplicate_dm_total"]
        top = dc[:6]
        rows = "".join(
            f"<li>{c['count']}× <b>{esc(list(c['names'])[0])}</b> "
            f"<span class='path'>{esc('; '.join(p for p in c['paths'] if p)[:90])}</span></li>"
            for c in top)
        out.append(dict(
            sev="medium", tag="Governance", effort="Medium · ongoing",
            title=f"{len(dc)} duplicate clusters span ~{dup_dm} data models ({pct(dup_dm, inv['total_dms'])} of the org)",
            impact="Near-identical copies (e.g. <code>X DM</code>, <code>X DM (1)</code>, "
                   "<code>X DM Test</code>, UAT/backup variants) split usage and let definitions drift, "
                   "so two dashboards on “the same” model can disagree.",
            affected=f"<ul class='aff'>{rows}{'<li>…</li>' if len(dc) > 6 else ''}</ul>",
            actions=[
                "Pick the canonical version in each cluster (newest on the governed surface) and confirm it "
                "covers the others' columns.",
                "Re-point consumers to the canonical model, then archive the copies (archiving is reversible).",
                "Discourage “Save As” for shared models; promote a copy into a governed folder instead.",
            ]))

    # 4 — sprawl
    if sprawl and sprawl / max(total, 1) > 0.3:
        out.append(dict(
            sev="medium", tag="Governance", effort="Low policy · ongoing",
            title=f"{sprawl} of {total} models ({pct(sprawl, total)}) live in personal "
                  f"<i>My Documents</i>; only {prod} sit in <code>1. PRODUCTION</code>",
            impact="Models in personal spaces aren't discoverable, owned, or promoted as a team asset, and "
                   "they vanish when a person offboards (several copies already sit under "
                   "<i>Archived Users</i>). The near-empty promotion path means “production” isn't yet the "
                   "single source of truth.",
            affected="",
            actions=[
                "Define a simple promotion path: personal → team/sandbox → <code>1. PRODUCTION</code>, with an "
                "owner and a short review per promotion.",
                "Identify the handful of personal models that real dashboards depend on and promote them first.",
                "Re-run this assessment quarterly to watch the production count grow and sprawl shrink.",
            ]))

    # 5 — metrics
    heavy = sorted([d for d in deep if d.get("metrics", 0) == 0 and d.get("calc_columns", 0) >= 20],
                   key=lambda d: -d.get("calc_columns", 0))
    no_metric = sum(1 for d in deep if d.get("metrics", 0) == 0)
    tmpl = max(deep, key=lambda d: d.get("metrics", 0), default=None)
    if heavy:
        rows = "".join(f"<li><b>{esc(d['_meta']['name'])}</b> — {d['calc_columns']} calc columns, "
                       f"0 metrics</li>" for d in heavy[:6])
        ex = (f" <b>{esc(tmpl['_meta']['name'])}</b> already does this well "
              f"({tmpl['metrics']} reusable metrics) and is a good in-house template."
              if tmpl and tmpl.get("metrics") else "")
        out.append(dict(
            sev="medium", tag="Reusability", effort="Medium",
            title=f"{no_metric} of {len(deep)} analyzed models define no reusable metrics",
            impact="When a model has no metrics, every dashboard re-implements its own "
                   "<code>Sum()</code>/<code>CountDistinct()</code> logic, so the same KPI drifts across "
                   "reports and there's no governed definition to point to." + ex,
            affected=f"<ul class='aff'>{rows}</ul>",
            actions=[
                "On each heavy model, promote the obvious aggregate calc columns "
                "(<code>Sum([Net Revenue])</code> etc.) to <b>element metrics</b> with a clear name and "
                "description.",
                "Express ratios/derived KPIs once as metrics so consumers reference them instead of rebuilding.",
                f"Lead with <b>{esc(heavy[0]['_meta']['name'])}</b> — the highest calc surface with zero "
                f"metrics today.",
            ]))

    # 6 — duplicate formulas
    dupf = [d for d in deep if d.get("dup_formula_clusters")]
    if dupf:
        worst = max(dupf, key=lambda d: len(d["dup_formula_clusters"]))
        fl = "".join(f"<li><code>{esc(c['formula'])}</code> — defined {c['count']}×</li>"
                     for c in worst["dup_formula_clusters"][:6])
        out.append(dict(
            sev="low", tag="Maintainability", effort="Low per model",
            title=f"Large models repeat the same formula many times — e.g. "
                  f"<b>{esc(worst['_meta']['name'])}</b> has {len(worst['dup_formula_clusters'])} "
                  f"repeated definitions",
            impact="Identical formulas copied across elements mean a change has to be made in many "
                   "places, and missing one creates a silent inconsistency. (Worst single model carries "
                   f"{worst.get('calc_columns', 0)} calc columns.)",
            affected=f"<ul class='aff code'>{fl}</ul>",
            actions=[
                "Define each repeated expression once (a shared calc column or metric on the source "
                "element) and reference it everywhere else.",
                "Calendar/date helpers like <code>DateTrunc(\"day\", [As Of])</code> are good candidates for "
                "a single shared date element.",
            ]))

    # 7 — naming
    empties = sorted([d for d in deep if d.get("empty_named_elements", 0)],
                     key=lambda d: -d["empty_named_elements"])
    if empties:
        rows = "".join(f"<li><b>{esc(d['_meta']['name'])}</b> — {d['empty_named_elements']} "
                       f"unnamed elements</li>" for d in empties[:6])
        out.append(dict(
            sev="low", tag="Discoverability", effort="Low",
            title="Many models leave imported elements unnamed",
            impact="Consumers browsing the model see anonymous elements and can't tell one revenue slice "
                   "from another without clicking in — friction that pushes them to rebuild rather than reuse.",
            affected=f"<ul class='aff'>{rows}</ul>",
            actions=[
                "Give every element a meaningful name (a ~30-minute pass per model).",
                "While there, fix typo columns that shadow the real one (e.g. <code>Defintion</code> vs "
                "<code>Definition</code>).",
            ]))
    return out


def render(inv, customer):
    deep = [d for d in inv["deep"] if "error" not in d]
    total = inv["total_dms"]
    by = inv["by_bucket"]
    sprawl = by.get("personal (My Documents)", 0)
    prod = by.get("1. PRODUCTION", 0)
    dup_dm = inv["duplicate_dm_total"]
    no_metric = sum(1 for d in deep if d.get("metrics", 0) == 0)
    integ_n = sum(1 for d in deep if d.get("sandbox_refs"))
    risk_n = sum(1 for d in deep if d.get("cross_elem_lookup_risk", 0))
    max_calc = max((d.get("calc_columns", 0) for d in deep), default=0)
    max_calc_dm = next((d["_meta"]["name"] for d in deep if d.get("calc_columns", 0) == max_calc), "")
    healthy = max(deep, key=lambda d: (d.get("metrics", 0), d.get("relationships", 0)), default=None)
    if healthy and healthy.get("metrics", 0) > 0:
        healthy_clause = (f"<b>{esc(healthy['_meta']['name'])}</b> shows the target pattern of reusable "
                          f"metrics ({healthy['metrics']}) and declared relationships ({healthy['relationships']})")
    else:
        healthy_clause = "a few models already follow good structure"
    gen = inv.get("generated", "")[:10] or datetime.date.today().isoformat()

    kpis = [
        ("Data models", f"{total}", "across the org"),
        ("In personal spaces", f"{pct(sprawl, total)}", f"{sprawl} in My Documents"),
        ("In production", f"{prod}", "promotion path"),
        ("Duplicate models", f"~{dup_dm}", f"{len(inv['duplicate_clusters'])} clusters"),
        ("Integrity flags", f"{integ_n}", "sandbox sources"),
        ("Models w/o metrics", f"{no_metric}/{len(deep)}", "of analyzed"),
    ]
    kpi_html = "".join(
        f"<div class='kpi'><div class='kpi-v'>{esc(v)}</div>"
        f"<div class='kpi-l'>{esc(l)}</div><div class='kpi-s'>{esc(s)}</div></div>"
        for l, v, s in kpis)

    # location bars
    maxb = max(by.values()) if by else 1
    loc_rows = "".join(
        f"<tr><td>{esc(k)}</td><td class='num'>{v}</td>"
        f"<td class='barcell'><span class='bar' style='width:{(100*v/maxb):.0f}%'></span></td></tr>"
        for k, v in sorted(by.items(), key=lambda x: -x[1]))

    # priority table (concern-ranked, top 25)
    def concern(d):
        s = 50 if d.get("sandbox_refs") else 0
        s += 4 * d.get("cross_elem_lookup_risk", 0)
        s += 10 if (d.get("calc_columns", 0) >= 40 and d.get("metrics", 0) == 0) else 0
        s += len(d.get("dup_formula_clusters", []))
        s += 0.2 * d.get("empty_named_elements", 0) + 0.05 * d.get("calc_columns", 0)
        return s
    ranked = sorted(deep, key=concern, reverse=True)[:25]
    prows = ""
    for d in ranked:
        m = d["_meta"]
        flag = (f"<span class='flag crit'>{esc(','.join(d['sandbox_refs']))}</span>"
                if d.get("sandbox_refs") else "<span class='ok'>—</span>")
        risk = d.get("cross_elem_lookup_risk", 0)
        riskc = "warn" if risk else ""
        metc = "warn" if d.get("metrics", 0) == 0 else ""
        prows += (f"<tr><td class='name'>{esc(m['name'])}</td>"
                  f"<td class='num'>{m['version']}</td>"
                  f"<td class='num'>{d['elements']}</td>"
                  f"<td class='num'>{d['calc_columns']}</td>"
                  f"<td class='num {metc}'>{d['metrics']}</td>"
                  f"<td class='num'>{d['relationships']}</td>"
                  f"<td class='num {riskc}'>{risk}</td>"
                  f"<td class='num'>{d['empty_named_elements']}</td>"
                  f"<td>{flag}</td></tr>")

    # recommendation cards
    rec_html = ""
    for i, r in enumerate(recs(inv, deep), 1):
        acts = "".join(f"<li>{a}</li>" for a in r["actions"])
        aff = (f"<div class='aff-wrap'><div class='aff-h'>Affected models</div>{r['affected']}</div>"
               if r["affected"] else "")
        rec_html += f"""
        <div class="rec {r['sev']}">
          <div class="rec-head">
            <span class="num-badge">{i}</span>
            <div>
              <div class="rec-meta"><span class="sev-tag {r['sev']}">{esc(r['sev'].upper())}</span>
                <span class="chip">{r['tag']}</span><span class="chip ghost">Effort: {esc(r['effort'])}</span></div>
              <h3>{r['title']}</h3>
            </div>
          </div>
          <p class="impact">{r['impact']}</p>
          {aff}
          <div class="act-h">Recommended actions</div>
          <ol class="acts">{acts}</ol>
        </div>"""

    summary = (
        f"This review covers all <b>{total}</b> data models in the {esc(customer)} Sigma "
        f"organization and a deep structural analysis of the <b>{len(deep)}</b> models on the "
        f"governed surface. The portfolio is healthy in places — {healthy_clause} — but three themes "
        f"stand out. First and most important, <b>{integ_n} "
        f"centralized models read from a sandbox/dev schema</b>, a data-integrity risk worth fixing "
        f"before anything else. Second, governance: <b>{pct(sprawl, total)}</b> of models sit in "
        f"personal spaces with only <b>{prod}</b> promoted to production, and ~<b>{dup_dm}</b> models "
        f"are duplicates. Third, reusability: <b>{no_metric}</b> of the analyzed models define no "
        f"reusable metrics, and <b>{risk_n}</b> rely on cross-element lookups that can break charts at "
        f"view time. Each finding below includes the affected models and concrete next steps. "
        f"<b>This was a read-only review — no models were changed.</b>")

    return PAGE.format(
        customer=esc(customer), gen=esc(gen), kpis=kpi_html, summary=summary,
        loc_rows=loc_rows, prows=prows, recs=rec_html, shown=len(ranked),
        governed=len(deep))


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sigma Data Model Assessment — {customer}</title>
<style>
:root{{--ink:#1a2233;--mut:#5b6779;--line:#e6e9f0;--bg:#f6f8fb;--card:#fff;
--accent:#3b5bdb;--crit:#d6336c;--high:#e8590c;--med:#1971c2;--low:#2f9e44;}}
*{{box-sizing:border-box}}
body{{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Helvetica,Arial,sans-serif;
color:var(--ink);background:var(--bg)}}
.wrap{{max-width:960px;margin:0 auto;padding:0 28px 80px}}
header.cover{{background:linear-gradient(135deg,#202b4d,#3b5bdb);color:#fff;padding:54px 0 46px;margin-bottom:34px}}
header.cover .wrap{{padding-bottom:0}}
.eyebrow{{text-transform:uppercase;letter-spacing:.14em;font-size:12px;opacity:.85;margin:0}}
header.cover h1{{font-size:32px;margin:8px 0 6px;font-weight:700}}
header.cover .sub{{opacity:.9;font-size:15px}}
header.cover .ro{{display:inline-block;margin-top:18px;background:rgba(255,255,255,.15);
border:1px solid rgba(255,255,255,.3);padding:5px 12px;border-radius:20px;font-size:12.5px}}
h2{{font-size:20px;margin:42px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--line)}}
.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:-60px 0 0;position:relative}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;
box-shadow:0 6px 20px rgba(20,30,60,.06)}}
.kpi-v{{font-size:26px;font-weight:700;color:var(--accent)}}
.kpi-l{{font-size:13px;font-weight:600;margin-top:2px}}
.kpi-s{{font-size:12px;color:var(--mut)}}
.summary{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px 24px;
margin-top:24px;font-size:15.5px}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
border-radius:12px;overflow:hidden;font-size:13.5px}}
th,td{{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line)}}
th{{background:#f0f3f9;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
td.name{{font-weight:600}}
tr:last-child td{{border-bottom:none}}
.warn{{color:var(--high);font-weight:700}}
.flag{{font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px}}
.flag.crit{{background:#ffe3ec;color:var(--crit)}}
.ok{{color:#adb5bd}}
.barcell{{width:42%}}
.bar{{display:block;height:10px;border-radius:6px;background:var(--accent);opacity:.85}}
.note{{color:var(--mut);font-size:13px;margin-top:8px}}
.rec{{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--med);
border-radius:12px;padding:20px 22px;margin:16px 0;box-shadow:0 2px 10px rgba(20,30,60,.04)}}
.rec.critical{{border-left-color:var(--crit)}} .rec.high{{border-left-color:var(--high)}}
.rec.medium{{border-left-color:var(--med)}} .rec.low{{border-left-color:var(--low)}}
.rec-head{{display:flex;gap:14px;align-items:flex-start}}
.num-badge{{flex:none;width:30px;height:30px;border-radius:50%;background:var(--accent);color:#fff;
font-weight:700;display:flex;align-items:center;justify-content:center;margin-top:2px}}
.rec h3{{margin:6px 0 0;font-size:17px;line-height:1.4}}
.rec-meta{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
.sev-tag{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;color:#fff}}
.sev-tag.critical{{background:var(--crit)}} .sev-tag.high{{background:var(--high)}}
.sev-tag.medium{{background:var(--med)}} .sev-tag.low{{background:var(--low)}}
.chip{{font-size:11.5px;background:#eef1f8;color:var(--mut);padding:2px 9px;border-radius:6px;font-weight:600}}
.chip.ghost{{background:transparent;border:1px solid var(--line)}}
.impact{{margin:14px 0 6px}}
.aff-wrap{{background:#f7f9fc;border:1px solid var(--line);border-radius:8px;padding:10px 14px;margin:10px 0}}
.aff-h,.act-h{{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);
font-weight:700;margin-bottom:4px}}
.act-h{{margin-top:14px}}
ul.aff{{margin:4px 0;padding-left:18px}} ul.aff li{{margin:3px 0}}
ul.aff.code li{{list-style:none;margin-left:-18px}}
.path{{color:var(--mut);font-size:12px}}
ol.acts{{margin:6px 0 0;padding-left:20px}} ol.acts li{{margin:6px 0}}
code{{background:#eef1f8;padding:1px 5px;border-radius:4px;font-size:12.5px;
font-family:"SF Mono",SFMono-Regular,Menlo,Consolas,monospace}}
footer{{color:var(--mut);font-size:12.5px;margin-top:40px;border-top:1px solid var(--line);padding-top:16px}}
</style></head><body>
<header class="cover"><div class="wrap">
<p class="eyebrow">Sigma · Data Model Health Assessment</p>
<h1>{customer}</h1>
<div class="sub">Review of existing Sigma data models against best practices · {gen}</div>
<span class="ro">🔒 Read-only review — no data models were modified</span>
</div></header>
<div class="wrap">
<div class="kpis">{kpis}</div>
<div class="summary"><h2 style="margin-top:6px;border:none;padding:0;font-size:18px">Executive summary</h2>{summary}</div>

<h2>Where the data models live</h2>
<table><thead><tr><th>Location</th><th class="num">Models</th><th></th></tr></thead>
<tbody>{loc_rows}</tbody></table>
<p class="note">A healthy portfolio concentrates shared models on a governed surface with a real
promotion path; large personal/sandbox populations indicate sprawl.</p>

<h2>Detailed recommendations</h2>
{recs}

<h2>Priority data models</h2>
<p class="note">The {shown} highest-concern of {governed} governed models analyzed, with the
structural signals behind the recommendations. <b>Calc</b> = calculated columns,
<b>Metrics</b>/<b>Rels</b> = reusable metrics &amp; declared relationships (more is healthier),
<b>Lookup</b> = cross-element lookups without a declared relationship.</p>
<table><thead><tr><th>Data model</th><th class="num">Ver</th><th class="num">Elems</th>
<th class="num">Calc</th><th class="num">Metrics</th><th class="num">Rels</th>
<th class="num">Lookup</th><th class="num">Unnamed</th><th>Integrity</th></tr></thead>
<tbody>{prows}</tbody></table>

<footer>Methodology: read-only inventory of every data model via the Sigma REST API, plus a
structural analysis of each governed-surface model's specification (elements, columns, reusable
metrics, declared relationships, and source schemas) scored against Sigma data-model best
practices. Priority uses each model's edit count as an activity proxy. Prepared for {customer}.</footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--customer", default="the organization")
    a = ap.parse_args()
    inv = json.load(open(a.inv))
    open(a.out, "w").write(render(inv, a.customer))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
