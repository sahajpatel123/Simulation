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
- **Safety**: Python dependency vulnerability scanner (`lint.yml`)
- **Trivy**: Container, filesystem, and Dockerfile configuration scanner (`security-scan.yml`)
- **CodeQL**: Semantic code analysis with the `security-and-quality` query suite (`codeql.yml`)
- **Gitleaks**: Git history and working-tree secret scanner (`backend-ci.yml`)
- **Actionlint + YAML/TOML validation**: GitHub Actions workflow syntax and security-policy checks (`workflow-validation.yml`)

The `workflow-validation.yml` job also enforces that every GitHub Action ref is pinned
to a full version tag and that every workflow declares least-privilege permissions.

### Running Security Checks Locally

```bash
# Python security lint
bandit -r backend/app

# Dependency vulnerability scans
pip-audit -r requirements.txt
safety check -r requirements.txt

# Secret scanning
gitleaks detect --config .github/gitleaks.toml
```

### Dependency Management

- Dependabot automatically creates security updates for dependencies
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

- [VERSION] - Initial security policy
