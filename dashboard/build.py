"""Build the public security dashboard from the CI pipeline's reports.

Every input is optional: a report missing because its job failed shows as "n/a"
rather than breaking the page. Standard library only, so CI needs no extra installs.

    python dashboard/build.py --reports reports --out site
"""

import argparse
import base64
import hashlib
import html
import json
import os
import re
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GATES = [
    ("test", "Tests + coverage", "pytest, Hypothesis", "Unit, API, and property-based tests. Fails below 100% coverage."),
    ("semgrep", "Static analysis", "Semgrep", "Scans the code, Dockerfile, and workflows for risky patterns."),
    ("gitleaks", "Secret scanning", "Gitleaks", "Searches the whole git history for leaked keys and tokens."),
    ("codeql", "Data-flow analysis", "CodeQL", "Traces untrusted input through the code to catch injection bugs."),
    ("build_scan", "Image scan + SBOM", "Trivy", "Blocks fixable high and critical CVEs and lists every package."),
    ("dast", "Live attack testing", "OWASP ZAP, Schemathesis", "Probes the running container and fuzzes every endpoint."),
    ("publish", "Sign + attest", "cosign, SLSA provenance", "Signs the image and records exactly how it was built."),
]
STATUS_LABELS = {"success": "Passed", "failure": "Failed", "cancelled": "Cancelled", "skipped": "Skipped"}
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
ZAP_RISKS = {"3": "High", "2": "Medium", "1": "Low", "0": "Informational"}
HISTORY_LIMIT = 30


def find(root: Path, pattern: str) -> Path | None:
    return next(iter(sorted(root.rglob(pattern))), None)


def load_json(path: Path | None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        return None


def tests_summary(root: Path) -> dict[str, Any] | None:
    path = find(root, "junit.xml")
    if not path:
        return None
    # Only three counters are needed, so read them with a regex instead of an XML
    # parser: no entity expansion or external entities to defend against.
    suites = re.findall(r"<testsuite\b([^>]*)>", path.read_text(encoding="utf-8", errors="replace"))
    if not suites:
        return None

    def count(attrs: str, name: str) -> int:
        match = re.search(rf'\b{name}="(\d+)"', attrs)
        return int(match[1]) if match else 0

    total = sum(count(s, "tests") for s in suites)
    failed = sum(count(s, "failures") + count(s, "errors") for s in suites)
    return {"total": total, "failed": failed}


def coverage_percent(root: Path) -> float | None:
    data = load_json(find(root, "coverage.json"))
    try:
        return round(float(data["totals"]["percent_covered"]), 2)
    except (TypeError, KeyError, ValueError):
        return None


def sarif_count(root: Path, pattern: str) -> int | None:
    paths = sorted(root.rglob(pattern))
    if not paths:
        return None
    count = 0
    for path in paths:
        data = load_json(path) or {}
        count += sum(len(run.get("results", [])) for run in data.get("runs", []))
    return count


def trivy_summary(root: Path) -> dict[str, Any] | None:
    data = load_json(find(root, "trivy.json"))
    if not isinstance(data, dict):
        return None
    fixable, unfixed = Counter(), Counter()
    for result in data.get("Results") or []:
        for vuln in result.get("Vulnerabilities") or []:
            bucket = fixable if vuln.get("FixedVersion") else unfixed
            bucket[vuln.get("Severity", "UNKNOWN")] += 1
    return {
        "fixable": {s: fixable[s] for s in SEVERITIES},
        "unfixed": {s: unfixed[s] for s in SEVERITIES},
        "total": sum(fixable.values()) + sum(unfixed.values()),
        "blocking": fixable["CRITICAL"] + fixable["HIGH"],
    }


def zap_summary(root: Path) -> dict[str, Any] | None:
    data = load_json(find(root, "zap-report.json"))
    if not isinstance(data, dict):
        return None
    counts = Counter()
    for site in data.get("site", []):
        for alert in site.get("alerts", []):
            counts[ZAP_RISKS.get(str(alert.get("riskcode")), "Informational")] += 1
    return {risk: counts[risk] for risk in ZAP_RISKS.values()}


def fuzz_summary(root: Path) -> dict[str, int] | None:
    path = find(root, "schemathesis.txt")
    if not path:
        return None
    match = re.search(r"(\d+) generated, (\d+) passed", path.read_text(encoding="utf-8", errors="replace"))
    return {"generated": int(match[1]), "passed": int(match[2])} if match else None


def sbom_components(root: Path) -> int | None:
    data = load_json(find(root, "sbom.cdx.json"))
    return len(data.get("components", [])) if isinstance(data, dict) else None


def previous_history(pages_url: str | None) -> list[dict[str, Any]]:
    if not pages_url:
        return []
    try:
        with urllib.request.urlopen(f"{pages_url.rstrip('/')}/history.json", timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read())
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def collect(reports: Path, env: dict[str, str]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "repository": env.get("GITHUB_REPOSITORY", ""),
        "commit": env.get("GITHUB_SHA", ""),
        "run_url": env.get("RUN_URL", ""),
        "image": env.get("IMAGE", ""),
        "digest": env.get("IMAGE_DIGEST", ""),
        "gates": {key: env.get(f"GATE_{key.upper()}", "unknown") for key, *_ in GATES},
        "tests": tests_summary(reports),
        "coverage": coverage_percent(reports),
        "semgrep_findings": sarif_count(reports, "semgrep.sarif"),
        "codeql_findings": sarif_count(reports, "codeql.sarif"),
        "trivy": trivy_summary(reports),
        "zap": zap_summary(reports),
        "fuzz": fuzz_summary(reports),
        "sbom_components": sbom_components(reports),
    }


def history_entry(data: dict[str, Any]) -> dict[str, Any]:
    trivy = data["trivy"] or {}
    return {
        "date": data["generated_at"],
        "commit": data["commit"][:7],
        "passed": all(v == "success" for v in data["gates"].values()),
        "tests": (data["tests"] or {}).get("total"),
        "coverage": data["coverage"],
        "blocking_vulns": trivy.get("blocking"),
        "total_vulns": trivy.get("total"),
    }


def badge(label: str, value: str, color: str) -> str:
    def width(text: str) -> int:
        return 10 + round(len(text) * 6.6)

    lw, vw = width(label), width(value)
    label, value = html.escape(label), html.escape(value)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{lw + vw}" height="20" role="img" '
        f'aria-label="{label}: {value}"><title>{label}: {value}</title>'
        f'<rect width="{lw}" height="20" fill="#555"/><rect x="{lw}" width="{vw}" height="20" fill="{color}"/>'
        f'<g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" text-anchor="middle">'
        f'<text x="{lw / 2}" y="14">{label}</text><text x="{lw + vw / 2}" y="14">{value}</text></g></svg>'
    )


GREEN, RED, AMBER, GREY = "#2e7d32", "#c62828", "#b26a00", "#6b7280"


def badges(data: dict[str, Any]) -> dict[str, str]:
    tests, cov, trivy = data["tests"], data["coverage"], data["trivy"]
    passed = all(v == "success" for v in data["gates"].values())
    return {
        "pipeline": badge("security gates", "passing" if passed else "failing", GREEN if passed else RED),
        "tests": badge("tests", f"{tests['total']} passed" if tests and not tests["failed"] else "n/a",
                       GREEN if tests and not tests["failed"] else GREY),
        "coverage": badge("coverage", f"{cov:g}%" if cov is not None else "n/a",
                          GREEN if cov == 100 else AMBER if cov is not None else GREY),
        "vulnerabilities": badge(
            "fixable high/critical",
            str(trivy["blocking"]) if trivy else "n/a",
            GREY if not trivy else GREEN if trivy["blocking"] == 0 else RED,
        ),
    }


STYLE = """
:root{--bg:#f6f7f9;--card:#fff;--fg:#1d2433;--muted:#5d6678;--line:#e3e6eb;--ok:#2e7d32;--bad:#c62828;--warn:#b26a00;--na:#6b7280}
@media (prefers-color-scheme:dark){:root{--bg:#0f1218;--card:#171b23;--fg:#e6e9ef;--muted:#9aa3b2;--line:#2a303b;--ok:#5cb85f;--bad:#ef5350;--warn:#f0a030;--na:#8a93a3}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 48px}h1{font-size:1.6rem;margin:0}h2{font-size:1.05rem;margin:32px 0 12px}
.sub{color:var(--muted);margin:4px 0 0}a{color:inherit}code{font-family:ui-monospace,Consolas,monospace;font-size:.85em;word-break:break-all}
.head{display:flex;gap:16px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap}
.summary{display:flex;align-items:center;gap:10px;font-weight:600;white-space:nowrap}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .k{color:var(--muted);font-size:.85rem}.card .v{font-size:1.6rem;font-weight:650;margin-top:2px}.card .n{color:var(--muted);font-size:.8rem}
.lead{color:var(--muted);margin:-4px 0 12px;max-width:760px}.desc{font-size:.85rem;margin-top:6px}
.gate-top{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}
.status{flex:none;font-size:.7rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;padding:2px 8px;border-radius:6px;border:1px solid currentColor}
.success{color:var(--ok)}.failure,.cancelled{color:var(--bad)}.skipped,.unknown{color:var(--na)}
pre{margin:6px 0 0;padding:12px 14px;background:var(--bg);border:1px solid var(--line);border-radius:8px;overflow-x:auto}
pre code{word-break:normal;white-space:pre}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:.9rem}
th,td{padding:8px 12px;text-align:right;border-bottom:1px solid var(--line)}th:first-child,td:first-child{text-align:left}
tr:last-child td{border-bottom:none}th{color:var(--muted);font-weight:600}.wrap{overflow-x:auto}
.mt{margin-top:8px}.ok-t{color:var(--ok)}.bad-t{color:var(--bad)}footer{color:var(--muted);font-size:.85rem;margin-top:32px}
"""


def render(data: dict[str, Any], history: list[dict[str, Any]]) -> str:
    e = html.escape
    na = "n/a"
    repo, commit = data["repository"], data["commit"]
    repo_url = f"https://github.com/{repo}"
    passed_count = sum(v == "success" for v in data["gates"].values())
    passed = passed_count == len(GATES)

    def gate_card(key: str, title: str, tools: str, description: str) -> str:
        result = data["gates"][key]
        status = result if result in STATUS_LABELS else "unknown"
        return (
            f'<div class="card"><div class="gate-top"><strong>{e(title)}</strong>'
            f'<span class="status {status}">{STATUS_LABELS.get(status, "No data")}</span></div>'
            f'<div class="n">{e(tools)}</div><div class="desc">{e(description)}</div></div>'
        )

    gate_cards = "".join(gate_card(*gate) for gate in GATES)

    tests, trivy, zap, fuzz = data["tests"], data["trivy"], data["zap"], data["fuzz"]

    def metric(label: str, value: str, note: str) -> str:
        return f'<div class="card"><div class="k">{e(label)}</div><div class="v">{e(value)}</div><div class="n">{e(note)}</div></div>'

    metrics = "".join(
        [
            metric("Tests", str(tests["total"]) if tests else na, f"{tests['failed']} failed" if tests else ""),
            metric("Coverage", f"{data['coverage']:g}%" if data["coverage"] is not None else na, "line + branch, gate at 100%"),
            metric("Fixable high/critical CVEs", str(trivy["blocking"]) if trivy else na, "Trivy gate, image must have 0"),
            metric("Fuzz cases", str(fuzz["generated"]) if fuzz else na, f"{fuzz['passed']} passed" if fuzz else "Schemathesis"),
            metric("Semgrep findings", str(data["semgrep_findings"]) if data["semgrep_findings"] is not None else na, "ERROR severity"),
            metric("CodeQL findings", str(data["codeql_findings"]) if data["codeql_findings"] is not None else na, "security-extended queries"),
            metric("ZAP warnings", str((zap["High"] + zap["Medium"] + zap["Low"])) if zap else na,
                   f"{zap['Informational']} informational" if zap else "OWASP ZAP API scan"),
            metric("SBOM components", str(data["sbom_components"]) if data["sbom_components"] is not None else na, "CycloneDX"),
        ]
    )

    if trivy:
        rows = "".join(
            f"<tr><td>{s.title()}</td><td>{trivy['fixable'][s]}</td><td>{trivy['unfixed'][s]}</td></tr>" for s in SEVERITIES
        )
        vuln_table = (
            '<div class="wrap"><table><tr><th>Severity</th><th>Fix available</th><th>No fix released</th></tr>'
            f"{rows}</table></div>"
        )
    else:
        vuln_table = f'<p class="sub">{na}</p>'

    supply = ""
    if data["digest"]:
        ref = f"{data['image']}@{data['digest']}"
        supply = (
            "<h2>Published image</h2>"
            '<p class="lead">The exact image this run released. Its digest changes if a single byte of the '
            "image changes, and the keyless cosign signature proves it was built by this repository's CI. "
            "It also carries SLSA build provenance and a CycloneDX SBOM.</p>"
            f'<div class="card"><div class="k">Image digest</div><code>{e(ref)}</code>'
            '<div class="k mt">Verify it yourself (requires cosign)</div>'
            f"<pre><code>cosign verify {e(ref)} \\\n"
            f"  --certificate-identity-regexp '^{e(repo_url)}/\\.github/workflows/ci\\.yml@' \\\n"
            "  --certificate-oidc-issuer https://token.actions.githubusercontent.com</code></pre></div>"
        )

    def commit_cell(sha: str) -> str:
        return f'<a href="{e(repo_url)}/commit/{e(sha)}"><code>{e(sha)}</code></a>' if sha else na

    trend_rows = "".join(
        f"<tr><td>{e(str(h.get('date', '')))}</td><td>{commit_cell(str(h.get('commit', '')))}</td>"
        f"<td class=\"{'ok-t' if h.get('passed') else 'bad-t'}\">{'pass' if h.get('passed') else 'fail'}</td>"
        f"<td>{e(str(h.get('tests', na)))}</td><td>{e(str(h.get('coverage', na)))}</td>"
        f"<td>{e(str(h.get('blocking_vulns', na)))}</td><td>{e(str(h.get('total_vulns', na)))}</td></tr>"
        for h in reversed(history)
    )

    style_hash = base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()
    commit_link = f'<a href="{e(repo_url)}/commit/{e(commit)}"><code>{e(commit[:7])}</code></a>' if commit else na
    run_link = f' · <a href="{e(data["run_url"])}">pipeline run</a>' if data["run_url"] else ""

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'sha256-{style_hash}'; img-src 'self'">
<meta name="referrer" content="no-referrer">
<title>autosec security dashboard</title><style>{STYLE}</style></head>
<body><main>
<div class="head"><div><h1>autosec security dashboard</h1>
<p class="sub">Live results from the CI pipeline that gates every release of <a href="{e(repo_url)}">{e(repo)}</a>.
Last run {e(data["generated_at"])} · commit {commit_link}{run_link}</p></div>
<div class="summary"><span class="status {'success' if passed else 'failure'}">{'Passing' if passed else 'Failing'}</span>
<span>{passed_count} of {len(GATES)} gates passed</span></div></div>
<h2>Security gates</h2>
<p class="lead">Every push runs these checks in order. A release is published only when all of them pass.</p>
<div class="grid">{gate_cards}</div>
<h2>Latest results</h2>
<p class="lead">Numbers from the most recent run on <code>main</code>.</p>
<div class="grid">{metrics}</div>
<h2>Container vulnerabilities</h2>
<p class="lead">Every known CVE in the published image, from Trivy. The gate fails on any high or critical CVE
that has a fix. The rest have no fix released yet, and Dependabot's base-image updates pick them up once one ships.</p>
{vuln_table}
{supply}
<h2>History</h2>
<p class="lead">One row per push to <code>main</code>, newest first (last 30). Fixable high/critical must stay at 0.
All CVEs should fall over time as upstream fixes land.</p>
<div class="wrap"><table><tr><th>Run</th><th>Commit</th><th>Gates</th><th>Tests</th>
<th>Coverage %</th><th>Fixable high/crit</th><th>All CVEs</th></tr>{trend_rows}</table></div>
<footer>Generated by <code>dashboard/build.py</code> from the reports each pipeline job uploads.
Raw data: <a href="data.json">data.json</a> · <a href="history.json">history.json</a></footer>
</main></body></html>
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    data = collect(args.reports, dict(os.environ))
    history = (previous_history(os.environ.get("PAGES_URL")) + [history_entry(data)])[-HISTORY_LIMIT:]

    (args.out / "badges").mkdir(parents=True, exist_ok=True)
    (args.out / "index.html").write_text(render(data, history), encoding="utf-8")
    (args.out / "data.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (args.out / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    for name, svg in badges(data).items():
        (args.out / "badges" / f"{name}.svg").write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    main()
