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

- **Bandit**: Python security linter for security issues
- **pip-audit**: Dependency vulnerability scanner
- **Trivy**: Container and configuration scanner
- **CodeQL**: Semantic code analysis for vulnerabilities

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