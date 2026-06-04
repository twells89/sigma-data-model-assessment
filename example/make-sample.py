#!/usr/bin/env python3
"""
Generate a fully synthetic inventory.json for the example report — no real customer
data. Fictional org "Northwind Trading Co. (sample)". Exercises every report signal
(integrity / lookup-risk / sprawl / duplicates / missing-metrics / dup-formulas /
unnamed-elements / a healthy template) so the rendered example mirrors a real run.

    python3 example/make-sample.py            # writes example/sample-inventory.json
"""
import json, os

HERE = os.path.dirname(__file__)


def el_deep(name, path, version, *, elements, calc, metrics, rels, lookup, empty,
            sandbox=None, dupf=None):
    d = {
        "_meta": {"name": name, "path": path, "version": version, "id": "sample-" + name[:6]},
        "elements": elements, "empty_named_elements": empty,
        "source_kinds": {}, "total_columns": calc + elements,
        "calc_columns": calc, "passthrough_columns": elements,
        "metrics": metrics, "relationships": rels, "lookup_columns": lookup,
        "aggregate_calc_cols": max(0, metrics // 2),
        "dup_formula_clusters": dupf or [], "typo_shadow_columns": [],
        "cross_elem_lookup_risk": lookup if rels == 0 and lookup else 0,
        "sandbox_refs": [sandbox] if sandbox else [],
    }
    return d


deep = [
    el_deep("Sales Mart DM", "0. CENTRALIZED/Sales", 180,
            elements=24, calc=190, metrics=0, rels=0, lookup=18, empty=9,
            dupf=[{"formula": 'DateTrunc("day", [As Of])', "count": 6},
                  {"formula": "[Gross Revenue] + [Adjustments]", "count": 4},
                  {"formula": 'DateAdd("day", -1, Today())', "count": 4}]),
    el_deep("Legacy Orders DM", "0. CENTRALIZED/Legacy", 60,
            elements=27, calc=50, metrics=0, rels=6, lookup=0, empty=14,
            sandbox="DEV_SANDBOX"),
    el_deep("Customer 360 DM", "0. CENTRALIZED/CRM", 80,
            elements=25, calc=28, metrics=11, rels=0, lookup=12, empty=10),
    el_deep("Inventory Snapshot DM", "0. CENTRALIZED/Ops", 40,
            elements=7, calc=30, metrics=0, rels=0, lookup=2, empty=2,
            sandbox="DEV_SANDBOX"),
    el_deep("Revenue Gold DM", "1. PRODUCTION", 210,
            elements=58, calc=100, metrics=64, rels=27, lookup=0, empty=48),
    el_deep("Marketing Spend DM", "0. CENTRALIZED/Marketing", 55,
            elements=20, calc=44, metrics=1, rels=0, lookup=2, empty=1),
    el_deep("Finance Targets DM", "FP&A/Models", 70,
            elements=18, calc=70, metrics=0, rels=0, lookup=0, empty=3),
    el_deep("Web Analytics DM", "0. CENTRALIZED/Digital", 33,
            elements=12, calc=30, metrics=8, rels=4, lookup=0, empty=1),
    el_deep("Returns DM", "0. CENTRALIZED/Ops", 22,
            elements=10, calc=25, metrics=0, rels=0, lookup=0, empty=6,
            sandbox="DEV_SANDBOX"),
    el_deep("Pricing DM", "FP&A/Models", 18,
            elements=8, calc=21, metrics=2, rels=0, lookup=1, empty=2),
]

by_bucket = {
    "personal (My Documents)": 78,
    "0. CENTRALIZED": 22,
    "FP&A": 9,
    "1. PRODUCTION": 1,
    "other shared": 12,
}
total = sum(by_bucket.values())

dup_clusters = [
    {"key": "sales mart dm", "count": 4,
     "names": ["Sales Mart DM", "Sales Mart DM (1)", "Sales Mart DM Test"],
     "paths": ["0. CENTRALIZED/Sales", "My Documents"]},
    {"key": "customer 360 dm", "count": 3,
     "names": ["Customer 360 DM", "Customer 360 DM (1)"],
     "paths": ["0. CENTRALIZED/CRM", "My Documents"]},
    {"key": "finance targets dm", "count": 3,
     "names": ["Finance Targets DM", "Finance Targets DM UAT"],
     "paths": ["FP&A/Models", "My Documents/Archived Users/j.doe"]},
    {"key": "returns dm", "count": 2, "names": ["Returns DM", "Returns DM (1)"],
     "paths": ["0. CENTRALIZED/Ops", "My Documents"]},
]
dup_total = sum(c["count"] for c in dup_clusters)

inv = {
    "base": "https://api.example.aws.sigmacomputing.com",
    "generated": "2026-06-04T00:00:00+00:00",
    "total_dms": total, "by_bucket": by_bucket,
    "duplicate_clusters": dup_clusters, "duplicate_dm_total": dup_total,
    "deep": deep,
    "consumer_coverage": {"workbooks_total": 0, "specs_read": 0, "specs_errored": 0,
                          "workbooks_with_dm_ref": 0, "consumer_counts_reliable": False},
}
out = os.path.join(HERE, "sample-inventory.json")
json.dump(inv, open(out, "w"), indent=2)
print("wrote", out)
