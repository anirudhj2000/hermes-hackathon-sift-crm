"""GET /api/evals/ — serve the eval reports written by backend/evals/run_evals.py.

Returns the latest run (per-suite dimension averages + case rows + Langfuse run
URLs) plus a short version history so the Evals page can show the trend across
prompt versions. Read-only; the reports directory is the source of truth.
"""

import json
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse

REPORTS_DIR = Path(settings.BASE_DIR) / "evals" / "reports"


def _summarize(suites):
    """suites = {suite: [{case, dimension, value, comment}]} ->
    {suite: {"overall": float, "dimensions": [{name, avg, n}], "cases": [...]}}"""
    out = {}
    for suite, rows in (suites or {}).items():
        by_dim = {}
        for r in rows:
            by_dim.setdefault(r["dimension"], []).append(r["value"])
        dims = [
            {"name": d, "avg": round(sum(v) / len(v), 3), "n": len(v)}
            for d, v in by_dim.items()
        ]
        vals = [r["value"] for r in rows]
        out[suite] = {
            "overall": round(sum(vals) / len(vals), 3) if vals else 0.0,
            "dimensions": sorted(dims, key=lambda d: d["avg"]),  # weakest first
            "cases": rows,
        }
    return out


def evals_summary(request):
    if not REPORTS_DIR.exists():
        return JsonResponse({"latest": None, "history": []})

    reports = []
    for path in REPORTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            data["_file"] = path.name
            data["_mtime"] = path.stat().st_mtime
            reports.append(data)
        except Exception:
            continue

    if not reports:
        return JsonResponse({"latest": None, "history": []})

    reports.sort(key=lambda r: r.get("_mtime", 0), reverse=True)
    latest = reports[0]

    payload = {
        "latest": {
            "ran_at": latest.get("ran_at"),
            "overall": latest.get("overall"),
            "client": latest.get("client"),
            "langfuse": latest.get("langfuse"),
            "git_sha": latest.get("git_sha"),
            "prompt_hash": latest.get("prompt_hash"),
            "urls": latest.get("urls", {}),
            "suites": _summarize(latest.get("suites", {})),
        },
        # newest-first, capped — one point per run for the trend line
        "history": [
            {
                "ran_at": r.get("ran_at"),
                "overall": r.get("overall"),
                "prompt_hash": r.get("prompt_hash"),
                "git_sha": r.get("git_sha"),
                "file": r.get("_file"),
            }
            for r in reports[:15]
        ],
    }
    return JsonResponse(payload)
