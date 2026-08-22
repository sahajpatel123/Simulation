# Branch Protection Rules Setup

This document describes how to configure branch protection rules for the TheCee repository to enforce security best practices.

## Recommended Branch Protection Settings for `main`

1. **Require a pull request before merging**
   - Enable: ✓ Require a pull request before merging
   - Require approvals: 1
   - Dismiss stale pull request approvals when new commits are pushed: ✓

2. **Require status checks to pass before merging**

   Check names must match the *displayed* check-run name (`name:` if set,
   otherwise the job id). Current names by workflow:

   | Workflow | Check name |
   |----------|------------|
   | backend-ci.yml | `pytest` |
   | lint.yml | `ruff (Python lint)` |
   | workflow-validation.yml | `Validate workflow syntax` |
   | workflow-validation.yml | `Validate CI hygiene (local parity script)` |
   | workflow-validation.yml | `Validate workflows with zizmor` |
   | security-scan.yml | `bandit (Python security)` |
   | security-scan.yml | `pip-audit (dependency CVEs)` |
   | security-scan.yml | `safety (Python advisory DB)` |
   | codeql.yml | `Analyze (python)`, `Analyze (javascript)` |
   | scorecard.yml | `Scorecard analysis` |

   Minimum required set (fast, blocking-worthy):
   `pytest`, `ruff (Python lint)`, `Validate CI hygiene (local parity script)`,
   `bandit (Python security)`, `pip-audit (dependency CVEs)`,
   `safety (Python advisory DB)`.

   > In this repo's solo/direct-push mode these gates matter most for
   > **Dependabot and automated PRs** — a red check blocks an auto-merge of a
   > bad dependency bump. Direct pushes by the maintainer bypass PR gating
   > by design.

3. **Require branches to be up to date before merging**
   - Enable: ✓ Require branches to be up to date before merging

4. **Include administrators**
   - Enable: ✓ Include administrators

5. **Restrict who can push to matching branches**
   - Enable: ✓ Restrict who can push to matching branches
   - Add team: `@sahajpatel123` (or authorized maintainers)

## GitHub CLI Commands to Set Up Branch Protection

```bash
# Set up branch protection for main.
# gh's -f flag cannot express nested arrays here reliably — pass JSON via --input.
cat <<'JSON' | gh api --method PUT --input - \
  repos/sahajpatel123/Simulation/branches/main/protection
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "pytest",
      "ruff (Python lint)",
      "Validate CI hygiene (local parity script)",
      "bandit (Python security)",
      "pip-audit (dependency CVEs)",
      "safety (Python advisory DB)"
    ]
  },
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "required_approving_review_count": 1
  },
  "enforce_admins": true,
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
```

## GitHub App for Automated Security

Consider installing:
- **GitHub Advanced Security** for:
  - Code scanning alerts
  - Secret scanning
  - Dependency review

## Security Integration Steps

1. Enable **Secret scanning** (+ push protection, validity checks,
   non-provider patterns) in repository settings — see SECURITY.md
   ("GitHub Repository Security Features"); verify with
   `gh api repos/<owner>/<repo> --jq .security_and_analysis`
2. Enable **Code scanning** with CodeQL (workflow already committed)
3. Enable **Dependabot security updates** in repository settings — the
   dependabot.yml version-bump config is separate from this toggle and does
   not enable it by itself
4. Set up **security advisories** for any discovered vulnerabilities
5. Configure **security overview** to track vulnerability status

## Additional Security Headers (for FastAPI)

Add to your FastAPI deployment:

```python
from fastapi.middleware import Middleware
from fastapi.middleware.security import SecurityMiddleware
from fastapi.middleware.cors import CORSMiddleware

# In your main app configuration.
# NOTE: allow_credentials stays False per the project decision log — JWT is
# sent via the Authorization header, never cookies.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

## Security Checklist for New Features

- [ ] Code passes bandit security scan
- [ ] Dependencies are not on vulnerability lists
- [ ] No secrets or credentials in code
- [ ] Input validation on all API endpoints
- [ ] Rate limiting on sensitive endpoints
- [ ] Proper error handling (no stack traces exposed)
- [ ] JWT tokens have correct expiration
- [ ] Database queries are parameterized

## Incident Response

If a vulnerability is discovered:
1. Create a private security advisory
2. Coordinate fix with maintainers
3. Publish security release
4. Update dependabot to patch if needed
5. Document lessons learned