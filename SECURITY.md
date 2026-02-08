# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it
responsibly.

### How to Report

1. **Do NOT open a public GitHub issue** for security vulnerabilities.
2. Instead, use [GitHub Private Vulnerability Reporting](https://github.com/loxone-prometheus-exporter/loxone-prometheus-exporter/security/advisories/new)
   to submit a confidential report.
3. Alternatively, email the maintainers directly (see `pyproject.toml` for contact info).

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 7 days
- **Fix release**: Within 30 days for critical issues

### Scope

The following are in scope:
- The exporter application code (`src/loxone_exporter/`)
- Docker image configuration
- CI/CD pipeline configuration
- Dependencies with known CVEs

The following are out of scope:
- Loxone Miniserver firmware vulnerabilities
- Prometheus/Grafana vulnerabilities (report to their respective projects)
- Issues requiring physical access to the network

## Security Best Practices for Users

1. **Network isolation**: Run the exporter on the same network segment as the
   Miniserver. Do not expose the WebSocket connection to the internet.
2. **Least privilege**: Create a dedicated Loxone user with minimal permissions
   for the exporter.
3. **Secrets management**: Use environment variables or mounted secrets for
   credentials — never commit passwords to version control.
4. **Container security**: Run the container as non-root (default) and use
   read-only filesystem mounts where possible.
5. **Monitoring**: Monitor the `/healthz` endpoint and set up alerts for
   connectivity issues.
