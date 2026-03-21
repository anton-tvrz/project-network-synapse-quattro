# ADR-0003: Local Development Migration

## Status

Accepted

## Date

2026-03-21

## Context

The previous project (project-network-synapse-3) ran workloads on GCP VMs connected via Tailscale, using a `develop`/`staging`/`main` branch model with automated deployment pipelines (`deploy.yml`) that SSH'd into VMs to pull code and restart services. This introduced cloud costs, network complexity (Tailscale mesh), deployment latency, and a multi-branch workflow with staging confidence gates.

With the availability of Apple Silicon hardware (MacBook M5) and OrbStack for lightweight container management, the full stack (Infrahub, Temporal, Containerlab, SR Linux) can run locally with equivalent or better performance than the GCP VM setup.

## Decision

All workloads run locally via Docker Compose and OrbStack on Apple Silicon. The branch model is simplified to `main` + feature branches only. PRs target `main` directly.

Specifically:

- **Infrastructure:** Docker Compose managed by OrbStack replaces GCP VMs + Tailscale
- **Branch model:** Single `main` branch replaces `main` / `develop` / `staging`
- **CI/CD:** `deploy.yml` workflow is removed entirely; `pr-validation.yml` targets `main` only
- **Secrets:** VM_SSH_KEY, VM_HOST, VM_USER secrets are no longer needed
- **Releases:** `release.yml` runs directly against `main` without a `develop` → `main` PR step

## Consequences

### Positive
- Zero cloud costs (no GCP VM billing)
- Faster iteration cycle (no SSH deploy latency, no staging pipeline wait)
- Simpler branch model (no develop/staging confusion, no staging confidence gates)
- OrbStack provides native Apple Silicon performance for Docker containers
- Fewer CI workflows to maintain (no deploy.yml, no staging-confidence checks)
- Reduced GitHub Secrets surface area

### Negative
- No remote staging environment for pre-production validation
- Containerlab topology limited to local machine resources
- Team collaboration requires each developer to run the full stack locally
- No automated deployment pipeline (manual `docker compose up` locally)
