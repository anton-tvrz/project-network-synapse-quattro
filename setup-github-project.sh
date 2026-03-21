#!/usr/bin/env bash
# setup-github-project.sh — Create GitHub labels for Network Synapse Quattro
# Run from repo root: bash setup-github-project.sh
set -euo pipefail

REPO=$(gh repo view --json nameWithOwner -q '.nameWithOwner')
echo "=== Setting up project labels for: $REPO ==="
echo ""

LABEL_COUNT=0

# ─────────────────────────────────────────────
# Labels
# ─────────────────────────────────────────────
echo "── Creating Labels ──"

create_label() {
  local name="$1" color="$2" desc="$3"
  gh label create "$name" --color "$color" --description "$desc" --force
  LABEL_COUNT=$((LABEL_COUNT + 1))
}

create_label "ci-cd"          "1D76DB" "CI/CD pipeline"
create_label "infrahub"       "0E8A16" "Infrahub source of truth"
create_label "temporal"       "5319E7" "Temporal workflows"
create_label "containerlab"   "D93F0B" "Containerlab topology"
create_label "testing"        "FBCA04" "Tests and coverage"
create_label "observability"  "006B75" "Monitoring and logging"
create_label "documentation"  "C5DEF5" "Docs and runbooks"
create_label "security"       "B60205" "Security and secrets"
create_label "srlinux"        "FF6600" "Nokia SR Linux"
create_label "ansible"        "EE0000" "Ansible playbooks"
create_label "skip-changelog" "EEEEEE" "Skip changelog requirement"
create_label "dependencies"   "0075CA" "Dependency updates"
create_label "backend"        "E0E0E0" "Backend package changes"
create_label "workers"        "E0E0E0" "Workers package changes"
create_label "infrastructure" "E0E0E0" "Infrastructure changes"
create_label "config"         "E0E0E0" "Configuration changes"
create_label "ai-integration" "8B5CF6" "AI-powered features"

echo "  ✓ $LABEL_COUNT labels created"
echo ""

# ─────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────
echo "═══════════════════════════════════════════"
echo "  GitHub Project Setup Complete"
echo "═══════════════════════════════════════════"
echo "  Labels created: $LABEL_COUNT"
echo ""
echo "  Next steps:"
echo "  1. Configure branch protection on main"
echo "  2. Add repo secrets: CODECOV_TOKEN, RELEASE_PAT"
echo "  3. Create a GitHub Project board"
echo "═══════════════════════════════════════════"
