import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dashboard"))
import build  # noqa: E402

ALL_PASS = {f"GATE_{key.upper()}": "success" for key, *_ in build.GATES}


def write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def reports(tmp_path):
    root = tmp_path / "reports"
    write(
        root,
        "test-reports/junit.xml",
        '<testsuites name="pytest tests"><testsuite name="pytest" errors="0" failures="0" tests="129"/>'
        '<testsuite name="extra" tests="0"/></testsuites>',
    )
    write(root, "test-reports/coverage.json", json.dumps({"totals": {"percent_covered": 100.0}}))
    write(root, "semgrep-reports/semgrep.sarif", json.dumps({"runs": [{"results": []}]}))
    write(root, "codeql-reports/codeql.sarif", json.dumps({"runs": [{"results": [{}, {}]}]}))
    write(
        root,
        "trivy-reports/trivy.json",
        json.dumps({"Results": [{"Vulnerabilities": [
            {"Severity": "HIGH", "FixedVersion": "1.2"},
            {"Severity": "HIGH"},
            {"Severity": "LOW"},
        ]}]}),
    )
    write(root, "dast-reports/zap-report.json", json.dumps({"site": [{"alerts": [{"riskcode": "0"}, {"riskcode": "2"}]}]}))
    write(root, "dast-reports/schemathesis.txt", "Test cases:\n  6397 generated, 6397 passed\n")
    write(root, "sbom/sbom.cdx.json", json.dumps({"components": [{}] * 102}))
    return root


def test_collects_every_report(reports):
    data = build.collect(reports, ALL_PASS)
    assert data["tests"] == {"total": 129, "failed": 0}
    assert data["coverage"] == 100.0
    assert data["semgrep_findings"] == 0
    assert data["codeql_findings"] == 2
    assert data["trivy"]["blocking"] == 1
    assert data["trivy"]["unfixed"]["HIGH"] == 1
    assert data["trivy"]["total"] == 3
    assert data["zap"] == {"High": 0, "Medium": 1, "Low": 0, "Informational": 1}
    assert data["fuzz"] == {"generated": 6397, "passed": 6397}
    assert data["sbom_components"] == 102


def test_missing_and_corrupt_reports_degrade_to_none(tmp_path):
    write(tmp_path, "test-reports/junit.xml", "<not xml")
    write(tmp_path, "test-reports/coverage.json", "{")
    write(tmp_path, "dast-reports/schemathesis.txt", "crashed")
    data = build.collect(tmp_path, {})
    for key in ("tests", "coverage", "semgrep_findings", "codeql_findings", "trivy", "zap", "fuzz", "sbom_components"):
        assert data[key] is None, key
    assert set(data["gates"].values()) == {"unknown"}
    page = build.render(data, [build.history_entry(data)])
    assert "Failing" in page
    assert "n/a" in page


def test_untrusted_values_are_escaped(reports):
    env = {**ALL_PASS, "GITHUB_REPOSITORY": "<script>alert(1)</script>", "IMAGE": "x", "IMAGE_DIGEST": "sha256:<b>"}
    page = build.render(build.collect(reports, env), [])
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "sha256:&lt;b&gt;" in page


def test_page_style_matches_its_csp_hash(reports):
    page = build.render(build.collect(reports, ALL_PASS), [])
    assert "style=\"" not in page
    assert "default-src 'none'" in page


def test_main_writes_site_and_caps_history(reports, tmp_path, monkeypatch):
    old = [{"date": str(i), "commit": "abc", "passed": True} for i in range(build.HISTORY_LIMIT + 5)]
    monkeypatch.setattr(build, "previous_history", lambda url: old)
    monkeypatch.setattr(sys, "argv", ["build.py", "--reports", str(reports), "--out", str(tmp_path / "site")])
    monkeypatch.setenv("GATE_TEST", "failure")
    build.main()
    site = tmp_path / "site"
    history = json.loads((site / "history.json").read_text())
    assert len(history) == build.HISTORY_LIMIT
    assert history[-1]["passed"] is False
    assert "0 of 7 gates passed" in (site / "index.html").read_text(encoding="utf-8")
    assert "failing" in (site / "badges" / "pipeline.svg").read_text()
    assert "1" in (site / "badges" / "vulnerabilities.svg").read_text()


def test_badges_reflect_results(reports):
    passing = build.badges(build.collect(reports, ALL_PASS))
    assert build.GREEN in passing["pipeline"] and build.GREEN in passing["coverage"]
    assert "129 passed" in passing["tests"]
    assert build.RED in passing["vulnerabilities"]
    empty = build.badges(build.collect(Path("does-not-exist"), {}))
    assert all("n/a" in empty[name] for name in ("tests", "coverage", "vulnerabilities"))


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self) -> bytes:
        return self.body


@pytest.mark.parametrize(
    "body,expected",
    [(b'[{"commit": "abc"}]', [{"commit": "abc"}]), (b'{"not": "a list"}', []), (b"<html>404</html>", [])],
)
def test_previous_history_reads_the_published_file(monkeypatch, body, expected):
    seen = []

    def fake_urlopen(url, timeout):
        seen.append(url)
        return FakeResponse(body)

    monkeypatch.setattr(build.urllib.request, "urlopen", fake_urlopen)
    assert build.previous_history("https://example.github.io/autosec/") == expected
    assert seen == ["https://example.github.io/autosec/history.json"]


def test_previous_history_tolerates_unreachable_site(monkeypatch):
    def offline(url, timeout):
        raise OSError("offline")

    monkeypatch.setattr(build.urllib.request, "urlopen", offline)
    assert build.previous_history(None) == []
    assert build.previous_history("https://example.github.io/autosec") == []
