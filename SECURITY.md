# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |
| dev     | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability in TheCee, please report it following responsible disclosure practices.

### How to Report

1. **Do not** open a public GitHub issue for security vulnerabilities
2. Use GitHub's private vulnerability reporting:
   <https://github.com/sahajpatel123/Simulation/security/advisories/new>
3. Include the following in your report:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Any suggested remediation

### What to Expect

- Acknowledgment of your report within 48 hours
- A more detailed response within 7 days
- Regular updates on the progress of the fix
- Credit in the security advisory (if desired)

## Security Practices

### GitHub Repository Security Features

This public repository runs every free GitHub-native security feature:

- **Secret scanning** — detects known credential formats pushed anywhere in
  the repo, including the full git history.
- **Secret scanning push protection** — blocks a push containing a recognized
  secret before it lands, rather than alerting after the fact.
- **Validity checks** — tests detected secrets against the provider to flag
  ones that are still live.
- **Non-provider patterns** — also matches generic high-entropy patterns not
  tied to a specific provider.
- **Dependabot security updates** — automatic PRs for dependencies with known
  CVEs, complementing the weekly pip-audit/Safety/Trivy scans.

> **Status 2026-08-25**: an API audit found all five of these flipped to
> `disabled` (they had been enabled on 2026-08-23). Re-enablement via the
> REST API (`PATCH /repos/…` → `security_and_analysis`) was attempted and is
> pending; if the token lacks the required admin scope, enable them under
> **Settings → Code security and analysis** — they are part of the project's
> security posture, not optional extras. Re-check anytime with
> `gh api repos/<owner>/<repo> --jq .security_and_analysis`.

### CI/CD Security Checks

This repository runs automated security scans:

- **Bandit**: Python security linter for security issues (`security-scan.yml`)
- **pip-audit**: Python dependency vulnerability scanner (`security-scan.yml`, `lint.yml`)
- **Safety**: Python dependency vulnerability scanner (`lint.yml`, `security-scan.yml`)
- **Trivy**: Container, filesystem, and Dockerfile configuration scanner (`security-scan.yml`)
- **npm audit**: Frontend dependency vulnerability scanner (`security-scan.yml`)
- **OSV scan**: queries OpenSSF's OSV database — the same one Scorecard's
  `Vulnerabilities` check uses — for every pinned Python and npm version;
  stdlib-only tool at `tools/osv_scan.py` (`security-scan.yml`)
- **CodeQL**: Semantic code analysis with the `security-and-quality` query suite (`codeql.yml`)
- **Scorecard**: OpenSSF supply-chain health checks with SARIF uploaded to Code Scanning (`scorecard.yml`)
- **Dependency Review**: PR-time gate on high-severity dependency changes (`dependency-review.yml`)
- **Gitleaks**: Git history and working-tree secret scanner (`backend-ci.yml`)
- **Gitleaks (scheduled)**: Weekly full-history secret scan to catch pre-existing leaks (`secret-scan.yml`)
- **Actionlint + YAML/TOML validation + zizmor**: GitHub Actions workflow syntax, security-policy, and workflow-security static-analysis checks; actionlint is downloaded from a pinned release and checksum-verified (`workflow-validation.yml` runs `tools/validate_ci.py` plus `zizmor`)

The `workflow-validation.yml` job also enforces that every GitHub Action ref is pinned
to a full 40-hex commit SHA (with the release version kept as a trailing comment),
that every non-`-r` pip install in a workflow pins an exact version, that direct pins
in `requirements.txt` match the generated hash-locked files CI installs from, that
every workflow declares least-privilege permissions and keeps zizmor's audits enabled,
and that no workflow grants `actions: write`. YAML files are parsed and invalid
workflow files fail the validator. (The `--require-hashes` flags themselves are repo
convention — visible in every install step above — not separately parsed by the
validator; the lock-sync check is what fails when locks go stale.)

Run `python3 tools/validate_ci.py` locally to check the same supply-chain,
permissions, YAML/TOML, security-policy, env-file tracking, and job-timeout
rules before pushing.

#### GitHub Actions hardening checklist

- Every action ref is pinned to a full 40-hex commit SHA (version kept as a
  trailing comment).
- Every external repo in `.pre-commit-config.yaml` is likewise pinned to a
  full 40-hex commit SHA — pre-commit runs that code locally on every
  commit, so mutable tags carry the same risk as unpinned actions.
  Dependabot has no pre-commit ecosystem, so these revs are bumped
  manually: resolve each release tag to its commit SHA and update the
  `rev:` line, keeping the version comment.
- The Dockerfile pins its base image by sha256 digest (`FROM python:3.11-slim@sha256:…`).
- Every workflow declares a top-level least-privilege `permissions` block;
  write scopes (e.g. `id-token`, `security-events`) are scoped to the job
  that needs them, not the workflow.
- No workflow grants `actions: write`; `id-token: write` is only allowed in
  the scorecard analysis job.
- Every checkout sets `persist-credentials: false`.
- Every job sets a positive `timeout-minutes`.
- Every workflow has a `workflow_dispatch` trigger.
- Artifact uploads fail with `if-no-files-found: error`.
- Workflows pass `zizmor` with `.github/zizmor.yml` (all rules enabled —
  SHA-everywhere satisfies the `unpinned-uses` audit).

### Running Security Checks Locally

```bash
# Python security lint
bandit -r backend/app

# Dependency vulnerability scans
pip-audit -r requirements.txt
safety check -r requirements.txt

# Secret scanning
gitleaks detect --config .github/gitleaks.toml

# Frontend dependency audit
npm audit --json

# Container/filesystem and Dockerfile config scan
trivy fs --ignore-unfixed --severity CRITICAL,HIGH .
trivy config ./Dockerfile

# Workflow-security static analysis
uvx zizmor@1.28.0 --config .github/zizmor.yml .github/workflows
```

### Dependency Management

- Dependabot automatically creates security updates for dependencies
- Dependabot watches Python, npm, GitHub Actions, and the Docker base image
- Direct dependencies are pinned to exact versions in `requirements.txt`;
  CI installs resolve through hash-locked files (see above)
- Regular audits are recommended

#### Dependency hash-locking (enforced)

Every pip install in CI and the Dockerfile is hash-locked:
`pip install --no-cache-dir --require-hashes -r <lock>`. OpenSSF Scorecard's
`PinnedDependencies` probe treats any non-flag argument to `pip install`
(including `package==version`) as unpinned; `--require-hashes` installs are
the accepted shape, and the per-artifact SHA-256s make builds reproducible.

Three locks are generated by `tools/gen_dependency_lock.py` (resolves via
`pip --dry-run --report`, fetches every file's sha256 from the PyPI JSON API):

- `requirements-lock.txt` — runtime image (Dockerfile).
- `requirements-pytest-lock.txt` — backend-ci superset; separate because the
  tools closure pins pydantic 2.9.2 (via safety-schemas) while runtime uses
  2.13.4.
- `requirements-tools-lock.txt` — ruff, bandit, pip-audit, safety, zizmor,
  PyYAML across lint / security-scan / workflow-validation.

After bumping `requirements.txt`, regenerate all three and verify locally
with one command:

```bash
tools/regen_locks.sh   # or: tools/regen_locks.sh runtime|pytest|tools
```

Resolution deliberately stays local: a workflow would need bare
`pip install --report` steps, which scorecard's PinnedDependencies probe
flags — the exact findings hash-locking closed. The per-lock spec files
(`tools/lock-specs/`) pin every direct requirement with `==`, so the same
python 3.11 / pip 26.2.1 pair reproduces identical output.

### Secrets Management

- Never commit secrets to the repository
- Use `.env` files (gitignored) for local development
- Use GitHub Secrets for CI/CD environments
- Rotate secrets if accidentally committed

### Secure Coding Practices

- Input validation on all API endpoints
- Proper authentication and authorization
- Rate limiting on sensitive endpoints
- Parameterized queries to prevent SQL injection
- Proper error handling without exposing internals: curated
  `ValueError` messages may be returned as 400 details; every other
  exception must be logged server-side and surfaced only as its class name
  via `app.core.safe_errors.safe_error_label` (regression tests:
  `tests/test_hardware_error_hygiene.py`, `tests/test_safe_errors.py`)

## Security Contact

For security concerns, please contact the project maintainers.

## Changelog

- 2026-08-07 - CI/CD security hardening: pinned all GitHub Actions to full version
  tags, enabled CodeQL `security-and-quality` queries, fixed the gitleaks config
  schema and added a gitleaks pre-commit hook plus a weekly full-history secret
  scan, made Bandit/pip-audit/Safety fail when scanners cannot run, enforced
  least-privilege workflow permissions, and added an env-file tracking guard.
- 2026-08-07 - Added Dependabot update groups, CODEOWNERS coverage for security
  config files, and documented the local security toolchain.
- 2026-08-07 - Added npm audit scanning for frontend dependencies, pinned the
  actionlint install to a release artifact instead of an unpinned script, and
  tightened the workflow validator to fail on invalid YAML and reject
  `actions: write`.
- 2026-08-07 - Added OpenSSF Scorecard supply-chain analysis with SARIF results
  uploaded to GitHub Code Scanning, and enabled Scorecard runs on pull requests.
- 2026-08-07 - Restricted `id-token: write` to the Scorecard workflow, validated
  `gitleaks.toml` in the workflow validator, and made scanner artifact uploads
  fail when reports are missing.
- 2026-08-07 - Added a Safety scan job to `security-scan.yml`, consolidating
  Python advisory checks in the security workflow alongside lint.
- 2026-08-08 - Added a local `tools/validate_ci.py` parity checker for the
  workflow-validation CI job so pinning/permissions/YAML/TOML/security-policy
  checks can run before pushing, and wired the CI job to the same script.
- 2026-08-08 - Added SHA-256 verification for the actionlint release download in
  `workflow-validation.yml` so CI refuses a tampered or mismatched tool artifact.
- 2026-08-08 - Extended `tools/validate_ci.py` to require a positive
  `timeout-minutes` on every CI job, preventing hung runs from burning runner
  time without a bound.
- 2026-08-08 - Fixed CI dependency/config failures: pinned `numpy` to a
  Python 3.11/scipy-compatible release, upgraded `safety` to a version
  compatible with `pip-audit`, and removed an invalid ruff `pyupgrade`
  config field.
- 2026-08-08 - Cleared the pre-existing ruff lint backlog across `backend/app`,
  fixed missing imports, and corrected the `projects.tags` JSONB server default
  so migrations can run on a fresh PostgreSQL database.
- 2026-08-08 - Made migrations create `pgcrypto` independently of `pgvector`
  so token backfills work on PostgreSQL images without the vector extension.
- 2026-08-08 - Made app startup tolerant of a missing `pgvector` extension so
  local/CI PostgreSQL instances without it can still start the backend.
- 2026-08-09 - Re-pinned `numpy`/`scipy` to a Python 3.11-compatible set and
  raised the backend-ci pytest timeout to 30 minutes after the suite outgrew
  the old 15-minute cap.
- 2026-08-10 - Added `zizmor` static workflow-security analysis to
  `workflow-validation.yml`, with `.github/zizmor.yml` disabling only the
  hash-pinning audit because this repo intentionally pins actions to full
  version tags and enforces that separately.
- 2026-08-10 - Added a `validate-ci-hygiene` pre-commit hook so the same
  workflow/security-policy checks run locally before commit.
- 2026-08-10 - Extended `tools/validate_ci.py` to require a
  `workflow_dispatch` trigger on every workflow so none can lose manual-run
  capability without a CI failure.
- 2026-08-10 - Extended `tools/validate_ci.py` to verify `.github/zizmor.yml`
  keeps hash-pinning disabled, matching the repo's full-version-tag policy.
- 2026-08-10 - Added `.github/zizmor.yml`, `tools/validate_ci.py`, and
  `.pre-commit-config.yaml` to CODEOWNERS so security/CI config files have
  explicit maintainer ownership.
- 2026-08-10 - Added Dependabot ignores for `numpy>=2.5` and `scipy>=1.18`,
  which require Python 3.12, so dependency updates can't silently break the
  project's Python 3.11 dependency resolution again.
- 2026-08-10 - Extended `tools/validate_ci.py` to require every
  `upload-artifact` step to set `if-no-files-found: error`, preventing silent
  scanner report gaps.
- 2026-08-10 - Added a `zizmor` pre-commit hook so workflow-security analysis
  runs locally before commit, alongside the CI hygiene validator.
- 2026-08-10 - Moved CodeQL workflow permissions to the workflow top level so
  least-privilege scopes are declared at the workflow boundary.
- 2026-08-10 - Extended `tools/validate_ci.py` to require a top-level
  `permissions` block on every workflow, matching the repo's current layout.
- 2026-08-10 - Added a GitHub Actions hardening checklist to `SECURITY.md`
  summarizing the enforced CI invariants.
- 2026-08-10 - Extended `tools/validate_ci.py` to require a `concurrency`
  block on every workflow so overlapping runs are canceled promptly.
- 2026-08-23 - Hardened the action-pinning policy from version tags to full
  40-hex commit SHAs across every workflow, enforced by `tools/validate_ci.py`;
  re-enabled zizmor's `unpinned-uses` audit; extended the validator to require
  exact-version pins on every workflow pip install; and documented the
  deliberate deferral of `--require-hashes` hash-locking (requires Linux-native
  wheel resolution) as an accepted risk.
- 2026-08-23 - Enabled all free GitHub-native repository security features
  for this public repo: secret scanning (+ push protection, validity checks,
  non-provider patterns) and Dependabot security updates. Documented in
  SECURITY.md as part of the required security posture.
- 2026-08-23 - Extended `tools/validate_ci.py` to require every Dockerfile
  `FROM` to pin its base image by sha256 digest, and digest-pinned
  `python:3.11-slim` — closing the last mutable-ref supply-chain surface
  (mutable base-image tags repoint when maintainers push).
- 2026-08-24 - Shipped full dependency hash-locking: `tools/gen_dependency_lock.py`
  plus three generated locks (`requirements-lock.txt`,
  `requirements-pytest-lock.txt`, `requirements-tools-lock.txt`); every CI and
  Dockerfile pip install now runs `--require-hashes`, closing the Scorecard
  `PinnedDependencies` findings that the earlier deferral documented.
- 2026-08-24 - Added a private vulnerability reporting link to this policy so
  the Scorecard `Security-Policy` check finds contactable content, replaced
  the obsolete hash-pinning-deferral exception with the enforced hash-locking
  flow, and refreshed the Actions hardening checklist for job-scoped write
  permissions.
- 2026-08-25 - Closed the last osv_scan parity gap: nested package-lock
  copies are now scanned (and deduplicated), matching scorecard's
  recursive osv-scanner — a vulnerable nested pin can no longer be
  CLEAN here but flagged there. Dependabot's lack of a pre-commit
  ecosystem documented as manual rev maintenance.
- 2026-08-25 - Extended the SHA-everywhere pinning policy to
  `.pre-commit-config.yaml`: all five external hook repos now pin full
  commit SHAs (versions kept as trailing comments), and a new
  `validate_pre_commit_pins` check in `tools/validate_ci.py` rejects any
  mutable tag so the policy cannot silently regress.
- 2026-08-24 - Extended `tools/osv_scan.py` to cover every Python pin source
  scorecard's recursive osv-scanner sees (`requirements*.txt`, all generated
  locks, `tools/lock-specs/*.txt`) instead of direct pins only — surfacing
  two frozen-transitive findings the earlier scans missed.
- 2026-08-24 - Removed the last unfixable advisory surface: replaced
  `python-jose[cryptography]` with `PyJWT==2.13.0` (python-jose depends on
  `ecdsa`, which OSV marks affected from version 0 with no fixed release —
  Minerva timing attack on P-256). JWT behavior is pinned by
  `tests/test_security_jwt_required_claims.py`. Also bumped the CI tools
  spec from pip 25.2 to 26.2.1 to clear eleven published pip advisories.
- 2026-08-25 - Audited every secret-comparison path: Razorpay webhook
  signatures (`billing.py`) and UI preview tokens (`ui_generation.py`)
  both verify through `hmac.compare_digest`, and API-token digests use
  keyed HMAC-SHA256 — no raw `==` secret comparisons exist. Also proved,
  against the raw SARIF of the newest CodeQL Python analysis, that the
  three oldest open Python alerts (stack-trace exposure, bad tag filter,
  incomplete URL sanitization) have zero current detections: their code
  was fixed weeks ago and GitHub's alert state machine simply never
  transitioned them to fixed. They stay open pending a maintainer
  dismissal decision; do not re-audit their flagged lines.
- 2026-08-25 - Completed a repo-wide parameterized-SQL audit: every
  dynamic statement binds values through named parameters and the only
  interpolated DDL uses static identifier tuples. Hardened the cluster
  sync's bulk UPDATE to emit row chunks bounded below PostgreSQL's
  65,535 per-statement bind-parameter ceiling (previously one statement
  sized `rows × 3`, which would fail opaquely if the registry grew),
  hoisted its function-local SQLAlchemy import to module top, and pinned
  the parameterized-SQL property with a regression test
  (`tests/test_cluster_sync.py`).
- 2026-08-25 - Hoisted all remaining function-local stdlib imports (26
  sites across 24 files — `json`, `datetime`, `math`, `collections`,
  `re`) to module tops per the repo's no-local-imports rule, and added a
  repo-wide AST guard (`tests/test_import_hygiene.py`) that fails any
  future function-local stdlib import. App-internal lazy imports stay
  allowed: several are deliberate cycle-breakers, and heavy optional
  dependencies (playwright) are legitimately deferred to use.
- 2026-08-25 - API audit caught a silent posture regression: all five
  GitHub-native security features (secret scanning, push protection,
  validity checks, non-provider patterns, Dependabot security updates)
  had been flipped back to disabled since their 2026-08-23 enablement.
  Feature list corrected to carry a live status note; re-enablement
  tracked until `.security_and_analysis` shows every feature enabled.
- [VERSION] - Initial security policy
