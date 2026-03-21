# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Email the maintainers directly or use GitHub's private vulnerability reporting feature
3. Include as much detail as possible: steps to reproduce, potential impact, and suggested fix

## Security Practices

This project uses the following security tools:

- **Bandit** — Static analysis for common security issues in Python code
- **Gitleaks** — Scans for hardcoded secrets in git history
- **detect-secrets** — Pre-commit hook to prevent secrets from being committed
- **GitHub SARIF** — Security results uploaded to GitHub Security tab

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x | Yes |
