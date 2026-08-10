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
2. Email security reports to the maintainers
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

### CI/CD Security Checks

This repository runs automated security scans:

- **Bandit**: Python security linter for security issues (`security-scan.yml`)
- **pip-audit**: Python dependency vulnerability scanner (`security-scan.yml`, `lint.yml`)
- **Safety**: Python dependency vulnerability scanner (`lint.yml`, `security-scan.yml`)
- **Trivy**: Container, filesystem, and Dockerfile configuration scanner (`security-scan.yml`)
- **npm audit**: Frontend dependency vulnerability scanner (`security-scan.yml`)
- **CodeQL**: Semantic code analysis with the `security-and-quality` query suite (`codeql.yml`)
- **Scorecard**: OpenSSF supply-chain health checks with SARIF uploaded to Code Scanning (`scorecard.yml`)
- **Dependency Review**: PR-time gate on high-severity dependency changes (`dependency-review.yml`)
- **Gitleaks**: Git history and working-tree secret scanner (`backend-ci.yml`)
- **Gitleaks (scheduled)**: Weekly full-history secret scan to catch pre-existing leaks (`secret-scan.yml`)
- **Actionlint + YAML/TOML validation + zizmor**: GitHub Actions workflow syntax, security-policy, and workflow-security static-analysis checks; actionlint is downloaded from a pinned release and checksum-verified (`workflow-validation.yml` runs `tools/validate_ci.py` plus `zizmor`)

The `workflow-validation.yml` job also enforces that every GitHub Action ref is pinned
to a full version tag, that every workflow declares least-privilege permissions,
and that no workflow grants `actions: write`. YAML files are parsed and invalid
workflow files fail the validator.

Run `python3 tools/validate_ci.py` locally to check the same supply-chain,
permissions, YAML/TOML, security-policy, env-file tracking, and job-timeout
rules before pushing.

#### GitHub Actions hardening checklist

- Every action ref is pinned to a full version tag or commit SHA.
- Every workflow declares a top-level least-privilege `permissions` block.
- No workflow grants `actions: write`; `id-token: write` is only allowed in
  `scorecard.yml`.
- Every checkout sets `persist-credentials: false`.
- Every job sets a positive `timeout-minutes`.
- Every workflow has a `workflow_dispatch` trigger.
- Artifact uploads fail with `if-no-files-found: error`.
- Workflows pass `zizmor` with `.github/zizmor.yml` (hash-pinning disabled
  because tag pinning is enforced separately).

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
- All dependencies are pinned to specific versions in `requirements.txt`
- Regular audits are recommended

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
- Proper error handling without exposing internals

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
- [VERSION] - Initial security policy
