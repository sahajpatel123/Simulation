# Branch Protection Rules Setup

This document describes how to configure branch protection rules for the TheCee repository to enforce security best practices.

## Recommended Branch Protection Settings for `main`

1. **Require a pull request before merging**
   - Enable: ✓ Require a pull request before merging
   - Require approvals: 1
   - Dismiss stale pull request approvals when new commits are pushed: ✓

2. **Require status checks to pass before merging**
   - Enable: ✓ Require status checks to pass before merging
   - Required checks:
     - `backend-ci/test` (pytest)
     - `lint/ruff` (Python linting)
     - `security-scan/bandit` (Python security)
     - `security-scan/pip-audit`, `security-scan/safety` (dependency security)

3. **Require branches to be up to date before merging**
   - Enable: ✓ Require branches to be up to date before merging

4. **Include administrators**
   - Enable: ✓ Include administrators

5. **Restrict who can push to matching branches**
   - Enable: ✓ Restrict who can push to matching branches
   - Add team: `@sahajpatel123` (or authorized maintainers)

## GitHub CLI Commands to Set Up Branch Protection

```bash
# Set up branch protection for main
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  /repos/{owner}/{repo}/branches/main/protection \
  -f required_status_checks.required_status_checks='["backend-ci/test", "lint/ruff", "security-scan/bandit", "security-scan/pip-audit"]' \
  -f required_status_checks.strict=true \
  -f required_pull_request_reviews.dismiss_stale_reviews=true \
  -f required_pull_request_reviews.required_approving_review_count=1 \
  -f enforce_admins=true
```

## GitHub App for Automated Security

Consider installing:
- **GitHub Advanced Security** for:
  - Code scanning alerts
  - Secret scanning
  - Dependency review

## Security Integration Steps

1. Enable **Secret scanning** in repository settings
2. Enable **Code scanning** with CodeQL
3. Enable **Dependabot security updates** (already configured)
4. Set up **security advisories** for any discovered vulnerabilities
5. Configure **security overview** to track vulnerability status

## Additional Security Headers (for FastAPI)

Add to your FastAPI deployment:

```python
from fastapi.middleware import Middleware
from fastapi.middleware.security import SecurityMiddleware
from fastapi.middleware.cors import CORSMiddleware

# In your main app configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],
    allow_credentials=True,
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