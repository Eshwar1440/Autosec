# autosec

**A car-finance and vehicle-safety API, shipped through a pipeline that blocks every release on security checks.**

[![ci](https://github.com/Eshwar1440/autosec/actions/workflows/ci.yml/badge.svg)](https://github.com/Eshwar1440/autosec/actions/workflows/ci.yml)
[![security gates](https://eshwar1440.github.io/autosec/badges/pipeline.svg)](https://eshwar1440.github.io/autosec/)
[![tests](https://eshwar1440.github.io/autosec/badges/tests.svg)](https://eshwar1440.github.io/autosec/)
[![coverage](https://eshwar1440.github.io/autosec/badges/coverage.svg)](https://eshwar1440.github.io/autosec/)
[![fixable high/critical](https://eshwar1440.github.io/autosec/badges/vulnerabilities.svg)](https://eshwar1440.github.io/autosec/)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Eshwar1440/autosec/badge)](https://scorecard.dev/viewer/?uri=github.com/Eshwar1440/autosec)

autosec is a FastAPI service that answers the questions people ask before and
after buying a car: what a loan or lease will really cost, what a car is worth,
and whether it has open safety recalls. It calculates payments to the exact
cent and pulls recall, complaint, and crash-test data from the US government's
NHTSA database by VIN.

Every change goes through an automated DevSecOps pipeline: tests, static
analysis, secret scanning, container scanning, and live attack testing. A
release is published only if all of them pass, and every published image is
signed so anyone can verify where it came from. The results are public on the
**[live security dashboard](https://eshwar1440.github.io/autosec/)**.

## Features

- **Financing:** loan quotes, amortization schedules, "what can I afford", and lease vs buy
- **Vehicle safety:** VIN decoding, recalls, owner complaints, and 5-star crash ratings from NHTSA
- **Fleet tools:** depreciation schedules, total cost of ownership, and batch inventory valuation
- **Exact money math:** `Decimal` throughout, never floating point
- **Security pipeline:** Semgrep, CodeQL, Gitleaks, Trivy, OWASP ZAP, and API fuzzing on every push
- **Verifiable releases:** cosign-signed images with SLSA provenance and an SBOM

## Quick start

Run the published image:

```bash
docker run --rm -p 8000:8000 ghcr.io/eshwar1440/autosec:latest
```

Then try it:

```bash
curl -s localhost:8000/vin/1G1FZ6S04K4100123/recalls
curl -s localhost:8000/quote -H 'content-type: application/json' \
  -d '{"vehicle_price":"30000","apr_percent":"6","term_months":60}'
```

The full API contract is at `http://localhost:8000/openapi.json`. To run from
source instead, see [Run locally](#run-locally).

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/healthz` | Liveness check |
| POST | `/quote` | Monthly payment, amount financed, total interest |
| POST | `/quote/schedule` | Month-by-month amortization table |
| POST | `/quote/affordability` | Highest vehicle price whose payment fits a monthly budget |
| POST | `/compare/lease-vs-buy` | Lease vs loan over the same term: payments, total paid, equity, net cost |
| GET  | `/vin/{vin}/decode` | Make, model, year, trim, powertrain, and assembly plant |
| GET  | `/vin/{vin}/recalls` | Safety recalls, with "do not drive" and "park outside" flags |
| GET  | `/vin/{vin}/complaints` | Owner complaint totals (crashes, fires, injuries, deaths) and the latest reports |
| GET  | `/vin/{vin}/ratings` | NCAP 5-star crash ratings and rollover risk |
| POST | `/depreciation` | Straight-line or double-declining-balance schedule down to salvage value |
| POST | `/tco` | Total cost of ownership: purchase, fuel, insurance, maintenance, interest, minus resale |
| POST | `/inventory/valuation` | Estimated values for a batch of up to 100 vehicles |
| GET  | `/openapi.json` | Machine-readable API contract |

### Financing

```bash
curl -s localhost:8000/quote -H 'content-type: application/json' \
  -d '{"vehicle_price":"30000","down_payment":"5000","trade_in_value":"3000",
       "sales_tax_percent":"7.25","apr_percent":"6","term_months":60}'
```

```json
{"sales_tax":"2175.00","amount_financed":"24175.00","monthly_payment":"467.37",
 "term_months":60,"total_of_payments":"28042.20","total_interest":"3867.20"}
```

- **`/quote/schedule`** takes the same body and returns every payment's
  principal, interest, and remaining balance. The last payment absorbs the
  rounding remainder so the balance lands on exactly $0.00.
- **`/quote/affordability`** takes `monthly_budget` instead of `vehicle_price`
  and finds the highest whole-cent price whose quoted payment fits, tax included.
- **`/compare/lease-vs-buy`** uses the standard US lease formula: depreciation
  fee plus rent charge, with the money factor derived from the lease APR and
  sales tax on each payment. It assumes the car is worth its residual value
  at the end of the term.

**Money handling.** All math uses `Decimal`, never `float`. Results are
rounded half-up to the cent and returned as strings, so clients can't lose
precision either. `2.675` rounds to `2.68`; a float would give `2.67`.

**Input rules.**

| Field | Range | Format |
|-------|-------|--------|
| `vehicle_price`, `monthly_budget` | > 0 to 10,000,000 | up to 2 decimal places |
| `down_payment`, `trade_in_value` | 0 to 10,000,000 | up to 2 decimal places |
| `apr_percent`, `loan_apr_percent`, `lease_apr_percent` | 0 to 36 | up to 4 decimal places |
| `sales_tax_percent` | 0 to 20 | up to 4 decimal places |
| `residual_percent` | > 0 to 95 | up to 4 decimal places |
| `term_months` | 12 to 96 | integer |

Decimals can be sent as JSON numbers or as plain decimal strings (`"1234.56"`).
Loose forms such as `"1e4"`, `" 25000"`, or `"25_000"` are rejected, and so
are unknown fields. The published OpenAPI patterns encode each field's range,
so the spec matches exactly what the server accepts. Rules that span several
fields (a down payment that covers the whole price, or a lease cap cost below
the residual) return a 422 in the same error format as any other validation error.

### Vehicle safety (NHTSA)

```bash
curl -s localhost:8000/vin/1G1FZ6S04K4100123/recalls
```

```json
{"vehicle":{"vin":"1G1FZ6S04K4100123","make":"CHEVROLET","model":"BOLT EV","model_year":2019,
  "electrification":"BEV (Battery Electric Vehicle)","manufacturer":"GENERAL MOTORS LLC", ...},
 "count":6,"do_not_drive":false,"park_outside":true,
 "recalls":[{"campaign_number":"23V845000","report_received":"2023-12-14", ...}, ...]}
```

The endpoints wrap NHTSA's free public APIs (the vPIC VIN decoder, Recalls,
Complaints, and NCAP Safety Ratings) and clean up what comes back:

- **VIN validation.** 17 characters, no `I`, `O`, or `Q`, and a correct 9th
  character check digit (49 CFR 565). Typos are rejected before any network call.
- **One shape.** NHTSA's APIs use three date formats (DD/MM/YYYY for recalls,
  MM/DD/YYYY for complaints, ISO 8601 elsewhere), mixed field casing,
  star ratings as strings, and an HTTP 400 instead of an empty list for
  unknown models. All of it comes back as consistent ISO dates, integers,
  and booleans.
- **Untrusted upstream.** NHTSA responses are treated as untrusted input.
  Make and model are URL-escaped before being placed in a request path.
  Malformed or unexpected responses become a clean `502`, never a crash.
  A VIN NHTSA can't decode returns `404`.
- **Caching.** Responses are cached for an hour, so the four endpoints share
  one VIN decode and repeat lookups don't re-hit NHTSA.

Recalls, complaints, and ratings are reported for the VIN's make, model, and
year, because NHTSA's public API doesn't track recalls per individual VIN.
Check remedy status for a specific vehicle with the manufacturer or at
[nhtsa.gov/recalls](https://www.nhtsa.gov/recalls).

### Fleet and dealer tools

```bash
curl -s localhost:8000/tco -H 'content-type: application/json' \
  -d '{"vehicle_price":"35000","down_payment":"5000","sales_tax_percent":"7","apr_percent":"6",
       "term_months":60,"years":5,"annual_miles":12000,"miles_per_gallon":"30",
       "fuel_price_per_gallon":"3.50","annual_insurance":"1500","annual_maintenance":"600",
       "maintenance_growth_percent":"10","annual_registration":"150"}'
```

```json
{"purchase_price_with_tax":"37450.00","resale_value":"15529.69","interest_after_period":"0.00",
 "total_cost":"46024.31","cost_per_year":"9204.86","cost_per_mile":"0.77","years":[...]}
```

- **`/depreciation`** supports straight-line and double-declining balance.
  Declining balance switches to straight-line once that writes off more, the
  usual accounting convention, so the asset always lands exactly on its
  salvage value in the final year.
- **`/tco`** gives a year-by-year breakdown. Loan interest is taken from the
  real amortization schedule and counted in the year it's paid. Interest
  still owed when the car is sold is included, cash purchases work (a down
  payment equal to the taxed price), and resale value assumes a fixed yearly
  depreciation rate (default 15%). For an EV, pass MPGe as `miles_per_gallon`
  and the price of 33.7 kWh as `fuel_price_per_gallon`.
- **`/inventory/valuation`** takes up to 100 vehicles (stock ID, MSRP, model
  year, mileage, condition) and returns an estimate for each, plus fleet totals.
  It's a transparent rule-of-thumb model, not market data:
  - 20% depreciation in year one, then 15% a year.
  - ±1% per 1,000 miles away from 12,000 miles a year, capped at ±20%.
  - Condition factors from 0.65 (poor) to 1.05 (excellent).
  - Estimates never exceed MSRP and never fall below 5% of it.

  Every factor used is returned in the response, so each number can be traced.

### Hardening

Every response carries `Cache-Control: no-store`, a `default-src 'none'` CSP,
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, and `Cross-Origin-Resource-Policy: same-origin`.
There is no `Server` header. Interactive `/docs` and `/redoc` are disabled;
load `/openapi.json` into any OpenAPI viewer instead.

## Run locally

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt     # Windows
# python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # macOS/Linux

.venv/Scripts/python -m pytest                                  # tests + 100% coverage gate
.venv/Scripts/python -m uvicorn app.main:app --reload           # http://127.0.0.1:8000
```

To run offline against recorded NHTSA data instead of the live service:

```bash
.venv/Scripts/python -m uvicorn tests.nhtsa_stub:app --port 9000
AUTOSEC_VPIC_URL=http://127.0.0.1:9000/vpic AUTOSEC_NHTSA_URL=http://127.0.0.1:9000/api \
  .venv/Scripts/python -m uvicorn app.main:app
```

## Tests

139 tests at 100% line and branch coverage (`app/` and `dashboard/`). The
build fails below 100%.

- **Example tests** pin hand-checked answers: $25,000 at 6% for 60 months is
  $483.32/month, a $35,000 lease at 58% residual is $491.54/month with tax,
  and a $10,000 asset on double-declining balance switches to straight-line
  in year 4. They also cover every validation rule, error shape, and
  security header.
- **Property-based tests** (Hypothesis) check invariants across hundreds of
  generated inputs per run:
  - Payments match an exact `Fraction` reference to the cent.
  - A higher APR never lowers the payment; a longer term never raises it.
  - Every schedule pays off exactly, and its balance never goes negative.
  - The affordability answer always fits the budget, and one cent more doesn't.
  - Every VIN with its computed check digit validates, and any other digit fails.
  - Depreciation always totals cost minus salvage and never dips below salvage.
  - More miles or more years never raise a car's estimated value, a better
    condition never lowers it, and no estimate exceeds MSRP.
- **NHTSA tests** run against `tests/nhtsa_stub.py`, a stand-in server that
  replays real NHTSA responses recorded for a 2019 Chevrolet Bolt EV (in
  `tests/fixtures/nhtsa/`). Mock transports cover outages, HTML error pages,
  malformed JSON, and untidy fields. The test suite never calls the real service.

## Container

```bash
docker build -t autosec .
docker run --rm -p 8000:8000 autosec
```

- Multi-stage build on a digest-pinned `python:3.13-slim`.
- Runs as non-root UID 10001, with a `HEALTHCHECK` against `/healthz`.
- Debian packages are upgraded at build time.
- pip is removed from the final image. Packages are installed in the builder
  stage and copied over, so nothing at runtime needs pip. Removing it also
  removes its vendored urllib3, msgpack, and setuptools, which carried
  fixable HIGH CVEs.

## CI/CD pipeline

`.github/workflows/ci.yml` runs on every push and pull request:

```
    test ─┐
 semgrep ─┤
gitleaks ─┼─► build-scan ──────► dast ───────────► publish ──────────────────► dashboard
  codeql ─┘   build image        ZAP API scan      push to GHCR                 (main only)
              Trivy gate         Schemathesis      cosign keyless signature     GitHub Pages
              CycloneDX SBOM     (vs NHTSA stub)   SLSA provenance + SBOM       + badges
```

Each stage only runs if everything before it passed. The image is built once,
then passed between jobs as an artifact, so the image that gets published is
byte-for-byte the one that was scanned and attacked.

| Stage | Tool | What it catches | Fails the build when |
|-------|------|-----------------|----------------------|
| Source | pytest + Hypothesis | Wrong math, broken validation, regressions | Any test fails or coverage < 100% |
| Source | Semgrep | Dangerous code patterns in Python, the Dockerfile, and workflows | Any ERROR-severity finding |
| Source | Gitleaks | Passwords, keys, and tokens anywhere in git history | Any secret found |
| Source | CodeQL (`security-extended`) | Data-flow vulnerabilities such as injection | Any error-level result |
| Image | Trivy | Known CVEs in OS and Python packages | Any HIGH/CRITICAL CVE with an available fix |
| Running app | OWASP ZAP API scan | Missing headers, info leaks, injection, misconfig, probed over HTTP | Any WARN or FAIL alert |
| Running app | Schemathesis | Crashes, 5xx errors, responses that break the OpenAPI contract, undocumented status codes, invalid data accepted | Any check fails (`schemathesis.toml`) |
| Publish | cosign + `actions/attest` | — | — (produces the signature and attestations) |

During DAST, the container is pointed at the NHTSA stub through environment
variables. ZAP and Schemathesis send thousands of requests per run, and
sending those to a government API on every push would be both rude and flaky.

### Visibility

- **Public dashboard.** Every job uploads its report (JUnit and coverage,
  Semgrep and CodeQL SARIF, Trivy JSON, the ZAP report, the Schemathesis
  summary, the SBOM). On `main`, the `dashboard` job turns them into a static
  page on GitHub Pages with the four README badges above and a 30-run history.
  It runs even when a gate fails, so the page shows the failure instead of
  going stale. The generator (`dashboard/build.py`) is standard-library-only
  Python, escapes every value it renders, and serves the page under a
  `default-src 'none'` CSP with a hash-pinned stylesheet.
- **GitHub Security tab.** Semgrep, CodeQL, and Trivy (high and critical)
  findings are uploaded as SARIF, so they appear as code-scanning alerts.
- **OpenSSF Scorecard.** `.github/workflows/scorecard.yml` runs the Open
  Source Security Foundation's Scorecard weekly and on every push to `main`.
  It's an independent check of the repo's security practices (pinned
  dependencies, token permissions, SAST, dependency updates, branch
  protection, and more). Results go to the Security tab and the public
  badge above.
- **Security policy.** [`SECURITY.md`](SECURITY.md) explains how to report a
  vulnerability privately.

### Supply-chain controls

- **Pinned everything.** Every third-party action is pinned to a full commit
  SHA. The Python base image, Semgrep, and ZAP containers are pinned by digest.
  A moved tag can't change what runs.
- **Least privilege.** The workflow token is read-only by default. Only the
  jobs that need write access get it (`security-events`, `packages`,
  `id-token`, `attestations`). Checkouts don't persist credentials.
- **SBOM.** Every build produces a CycloneDX SBOM of the image: OS packages
  plus Python dependencies.
- **Signing.** Published images are signed with cosign in keyless mode, using
  GitHub's OIDC identity and recorded in Sigstore's public transparency log.
  No long-lived signing key exists.
- **Provenance.** A SLSA build-provenance attestation and an SBOM attestation
  are attached to the image digest in the registry.
- **Dependabot** (`.github/dependabot.yml`) opens weekly update PRs for pip
  packages, the Docker base image, and GitHub Actions. Each PR goes through
  the full pipeline.

### Verify a published image

```bash
IMAGE=ghcr.io/eshwar1440/autosec@sha256:<digest>

# Signature: proves the image came from this repo's CI workflow
cosign verify "$IMAGE" \
  --certificate-identity-regexp '^https://github.com/Eshwar1440/autosec/\.github/workflows/ci\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# Provenance and SBOM attestations
gh attestation verify "oci://$IMAGE" --owner Eshwar1440
```

## What the tooling actually caught

These issues came up during development and were fixed:

- **Trivy:** the first image had 5 fixable HIGH CVEs in pip's vendored
  packages, and the Debian base had HIGH CVEs in `apt`. Removing pip and
  upgrading OS packages cleared 10 CVEs (6 HIGH). The remaining HIGH findings
  are Debian packages with no fix released yet. The gate skips those by design,
  and Dependabot base-image updates pick up fixes as they ship.
- **Schemathesis:**
  - The OpenAPI spec advertised *any* string as a valid amount (even `""`),
    while the server rejected them. The schema now publishes the exact
    decimal format.
  - Malformed JSON returned an undocumented 400. That response is now documented.
  - Field patterns allowed values above each field's limit (an APR of 99).
    Each pattern now encodes its real range.
- **Hypothesis:**
  - On small loans, cent-rounded payments retired the balance before the
    final month and drove it negative. Schedules now end early, as a real
    lender's would.
  - It also found an edge case in the test generator itself: a $0.01 car
    with a 99% down payment rounds to "nothing to finance".
- **Semgrep:** the first version of the dashboard generator read the JUnit
  report with Python's built-in XML parser, which is open to entity-expansion
  attacks on untrusted input. It now reads the three counters it needs with
  a narrow regex, and has no XML parser at all.
- **ZAP:** the scan of the hardened container probes every route in the
  OpenAPI spec (14 URLs), passes 120 rules, and reports only two informational alerts. Both are
  expected: the 4xx responses its attack probes trigger, and "non-storable
  content", which is the intentional `Cache-Control: no-store`.

## Repository layout

```
app/main.py                 app setup, lifespan, security headers, error handlers
app/nhtsa.py                NHTSA client: VIN check digit, normalization, caching
app/calc/                   Decimal math: loans, leases, depreciation, TCO, valuation
app/models/                 request/response models and strict decimal types
app/routes/                 financing, vehicle-safety, and fleet endpoints
tests/                      example, property-based, and NHTSA tests
tests/nhtsa_stub.py         offline NHTSA stand-in (tests and CI DAST)
tests/fixtures/nhtsa/       recorded NHTSA responses
dashboard/build.py          builds the public security dashboard from CI reports
Dockerfile                  multi-stage, non-root, pip-free runtime
schemathesis.toml           API fuzzing checks
.github/workflows/ci.yml    the pipeline
.github/workflows/scorecard.yml  OpenSSF Scorecard
.github/dependabot.yml      dependency update automation
SECURITY.md                 how to report a vulnerability
```
