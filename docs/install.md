# Network Synapse Quattro -- Local macOS Installation Guide

Step-by-step guide for setting up Network Synapse Quattro on a local macOS machine.
Everything runs locally -- no cloud VMs, no remote access setup needed.

---

## Prerequisites Summary

| Requirement | Specification |
| ----------- | ------------- |
| **Machine** | MacBook with Apple Silicon (M-series), 32GB RAM recommended |
| **OS** | macOS 14+ (Sonoma or later) |
| **Container Runtime** | OrbStack (recommended) or Docker Desktop |
| **Steps 1-5** | Core platform (required) |
| **Step 6** | Containerlab network lab (required for integration testing) |
| **Step 7** | Worker + full verification (required) |
| **Step 8** | Observability (optional) |

---

## Step 1: Prerequisites (macOS + Homebrew + OrbStack)

**Purpose:** Install base tooling on macOS.

### 1.1 Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 1.2 Install OrbStack

OrbStack is recommended over Docker Desktop for better performance on Apple Silicon.

```bash
brew install orbstack
```

Launch OrbStack from Applications and complete the initial setup. OrbStack provides a
drop-in replacement for Docker CLI and Docker Compose.

### 1.3 Install System Dependencies

```bash
brew install jq git
```

### Verification

```bash
docker --version            # Expect: Docker version 24+ (provided by OrbStack)
docker compose version      # Expect: Docker Compose version v2.20+
docker run hello-world      # Expect: "Hello from Docker!" message
git --version               # Expect: git version 2.39+
jq --version                # Expect: jq-1.7+
```

---

## Step 2: Python 3.12 + uv Package Manager

**Purpose:** Install Python 3.12 and the uv package manager.

### 2.1 Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env
```

uv will automatically manage Python 3.12 for the project (specified in `pyproject.toml`).

### Verification

```bash
uv --version                # Expect: uv 0.5+ (or latest)
uv python list | grep 3.12  # Expect: Python 3.12 listed or downloadable
```

---

## Step 3: Clone + Install Dependencies

**Purpose:** Clone the repository, initialize submodules, and install all Python dependencies.

### 3.1 Clone the Repository

```bash
git clone https://github.com/anton-tvrz/project-network-synapse-quattro.git
cd project-network-synapse-quattro
```

### 3.2 Initialize Git Submodules

```bash
git submodule update --init --recursive
```

### 3.3 Set Up Environment Variables

```bash
cp .env.example .env

# The default Infrahub admin token is pre-configured in .env.example:
# INFRAHUB_API_TOKEN=06438eb2-8019-4776-878c-0941b1f1d1ec
# No manual token creation needed.
```

### 3.4 Install Python Dependencies

```bash
# Install all dependency groups (testing, linting, typing, dev)
uv sync --all-groups
```

### 3.5 Install Pre-commit Hooks

```bash
uv run pre-commit install
```

### Verification

```bash
# Verify packages are importable
uv run python -c "import network_synapse; print('backend OK')"
uv run python -c "import synapse_workers; print('workers OK')"

# Verify invoke task runner works
uv run invoke --list

# Verify submodule is populated
ls library/schema-library/base/
# Expect: directory listing with schema YAML files

# Verify project structure
ls backend/ workers/ tests/ tasks/ dev/ development/ containerlab/
```

### Troubleshooting

| Issue | Fix |
| --- | --- |
| `uv sync` fails with resolver error | Delete `uv.lock` and run `uv lock && uv sync --all-groups` |
| Submodule clone fails | Check GitHub access: `ssh -T git@github.com` or use HTTPS |
| Import errors after install | Ensure you ran `uv sync --all-groups` (not just `uv sync`) |
| `invoke: command not found` | Always run via `uv run invoke`, not bare `invoke` |

---

## Step 4: Start Infrastructure

**Purpose:** Start the full infrastructure stack (12 containers) via Docker Compose.
OrbStack runs containers with near-native performance on Apple Silicon.

### 4.1 Start All Infrastructure Containers

```bash
uv run invoke dev.deps
```

This runs `docker compose -f development/docker-compose-deps.yml up -d` under the hood,
starting all 12 containers (~10GB total memory reserved).

### 4.2 Wait for Services to Initialize

Infrahub takes 60-90 seconds to fully initialize (Neo4j and the task-manager must be
ready first, then Infrahub applies migrations).

```bash
# Watch container status until all are running
docker compose -f development/docker-compose-deps.yml ps

# Wait for Infrahub to respond
echo "Waiting for Infrahub..."
for i in $(seq 1 24); do
  if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000 | grep -q "200\|301\|302"; then
    echo "Infrahub is ready!"
    break
  fi
  echo "  Attempt $i/24 -- waiting 5s..."
  sleep 5
done
```

### Services Reference (12 containers total)

**Infrahub Stack (7 containers):**

| Service | Container | Port | Health Check |
| --- | --- | --- | --- |
| Neo4j | infrahub-database | 7687, 7474 | `curl http://localhost:7474` |
| Redis | infrahub-cache | 6379 | `docker exec <id> redis-cli ping` |
| RabbitMQ | infrahub-message-queue | 5672, 15672 | `curl http://localhost:15672` (guest/guest) |
| PostgreSQL | task-manager-db | 5433 | Task manager database |
| Task Manager | task-manager | 4200 | `curl http://localhost:4200` (Prefect API) |
| Infrahub Server | infrahub-server | 8000 | `curl http://localhost:8000` |
| Task Worker | task-worker | -- | Background task processor |

**Temporal Stack (3 containers):**

| Service | Container | Port | Health Check |
| --- | --- | --- | --- |
| PostgreSQL | temporal-db | 5432 | Temporal persistence |
| Temporal | temporal | 7233 | `curl http://localhost:8080` (via UI) |
| Temporal UI | temporal-ui | 8080 | `curl http://localhost:8080` |

**Observability (2 containers):**

| Service | Container | Port | Health Check |
| --- | --- | --- | --- |
| Prometheus | prometheus | 9090 | `curl http://localhost:9090` |
| Grafana | grafana | 3000 | `curl http://localhost:3000` (admin/synapse) |

> **Note:** SuzieQ is commented out in docker-compose (broken on Apple Silicon).

### Verification

```bash
# All 12 containers running
docker compose -f development/docker-compose-deps.yml ps | grep -c "running"
# Expect: 12

# Infrahub API responds
curl -s http://localhost:8000 | head -c 200

# Temporal UI responds
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080
# Expect: 200

# Task Manager (Prefect API) responds
curl -s -o /dev/null -w "%{http_code}" http://localhost:4200/api/health
# Expect: 200
```

### Troubleshooting

| Issue | Fix |
| --- | --- |
| Infrahub image pull fails | May need `docker login registry.opsmill.io` |
| Neo4j OOM killed | Set `NEO4J_server_memory_heap_max__size=1G` in compose environment |
| Port conflict | Check: `lsof -i :<PORT>`. Override port in `.env` |
| Infrahub stuck starting | Check logs: `docker compose -f development/docker-compose-deps.yml logs infrahub-server --tail 50` |
| Not enough memory | All 12 containers reserve ~10GB total. Ensure sufficient RAM available. |
| Task-manager not starting | Ensure task-manager-db (postgres) is healthy first. Check logs: `docker compose -f development/docker-compose-deps.yml logs task-manager --tail 50` |

---

## Step 5: Load Schemas + Seed Data

**Purpose:** Load Infrahub schemas, seed the network topology data, and verify the
config generation pipeline works.

### 5.1 Load Schemas into Infrahub

The default admin API token is pre-configured in `.env.example`
(`06438eb2-8019-4776-878c-0941b1f1d1ec`). No manual token creation is needed.

**Option A: Use the invoke task (recommended):**

```bash
uv run invoke backend.load-schemas
```

**Option B: Use `infrahubctl` CLI directly:**

```bash
export INFRAHUB_ADDRESS=http://localhost:8000
export INFRAHUB_API_TOKEN=06438eb2-8019-4776-878c-0941b1f1d1ec

# Load base schemas from the schema-library submodule
uv run infrahubctl schema load library/schema-library/base/*.yml

# Load routing extensions
uv run infrahubctl schema load \
  library/schema-library/extensions/vrf/vrf.yml \
  library/schema-library/extensions/routing/routing.yml \
  library/schema-library/extensions/routing_bgp/bgp.yml

# Load project-specific schemas
uv run infrahubctl schema load \
  backend/network_synapse/schemas/network_device.yml \
  backend/network_synapse/schemas/network_interface.yml
```

### 5.2 Seed Network Topology Data

```bash
uv run invoke backend.seed-data
```

This creates:

- 3 devices: spine01 (AS65000), leaf01 (AS65001), leaf02 (AS65002)
- 11 interfaces across all devices (fabric, loopback, management)
- 4 eBGP sessions (spine-to-leaf peerings)
- Organizations, locations, platforms, autonomous systems, IP prefixes

### 5.3 Test Config Generation

```bash
# Dry run -- renders configs without writing files
uv run invoke backend.generate-configs --dry-run

# Full run -- writes to generated-configs/<hostname>/
uv run invoke backend.generate-configs
```

### Verification

```bash
# Query Infrahub for devices (should return 3)
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "{ DcimDevice { edges { node { hostname { value } } } } }"}' \
  | jq '.data.DcimDevice.edges | length'
# Expect: 3

# Check generated config files exist
ls generated-configs/
# Expect: spine01/ leaf01/ leaf02/ directories
```

### Troubleshooting

| Issue | Fix |
| --- | --- |
| `load-schemas` fails with connection error | Verify Infrahub is running: `curl http://localhost:8000`. Infrahub needs 60-90s after startup. |
| `seed-data` fails with 409 conflict | Data already exists. If persistent, restart with fresh volumes: `docker compose -f development/docker-compose-deps.yml down -v && uv run invoke dev.deps` |
| `generate-configs` can't connect | Ensure `INFRAHUB_URL=http://localhost:8000` in `.env` |
| GraphQL query returns empty | Schemas not loaded -- run `load-schemas` before `seed-data` |
| `infrahubctl` auth error | Ensure `INFRAHUB_API_TOKEN=06438eb2-8019-4776-878c-0941b1f1d1ec` is set (default admin token) |

---

## Step 6: Containerlab + Nokia SR Linux Lab

**Purpose:** Install Containerlab and deploy the 3-node Nokia SR Linux spine-leaf
network topology.

### 6.1 Install Containerlab

```bash
bash -c "$(curl -sL https://get.containerlab.dev)"
```

### 6.2 Pull Nokia SR Linux Image

```bash
docker pull ghcr.io/nokia/srlinux:latest
```

> **Note:** If the pull fails with auth errors, you may need to authenticate:
> `echo <GHCR_TOKEN> | docker login ghcr.io -u <USERNAME> --password-stdin`

### 6.3 Deploy the Topology

```bash
sudo containerlab deploy --topo containerlab/topology.clab.yml
```

This creates:

- **spine01** (Nokia SR Linux IXR-D3) -- 4 fabric links
- **leaf01** (Nokia SR Linux IXR-D2) -- 2 uplinks to spine
- **leaf02** (Nokia SR Linux IXR-D2) -- 2 uplinks to spine
- Management network: `172.20.20.0/24`

With OrbStack, the `172.20.20.x` container IPs are directly accessible from macOS --
no tunnels or routing needed.

### 6.4 Verify Topology

```bash
# List deployed nodes
sudo containerlab inspect --topo containerlab/topology.clab.yml
# Expect: 3 nodes with status "running"

# Verify all nodes are reachable (directly from macOS)
for node in spine01 leaf01 leaf02; do
  echo -n "$node: "
  docker exec clab-spine-leaf-lab-$node sr_cli "show version" 2>/dev/null | head -1 || echo "FAILED"
done
```

### Fabric Links

| Link | Endpoint A | Endpoint B |
| --- | --- | --- |
| 1 | spine01:e1-1 | leaf01:e1-49 |
| 2 | spine01:e1-2 | leaf02:e1-49 |
| 3 | spine01:e1-3 | leaf01:e1-50 |
| 4 | spine01:e1-4 | leaf02:e1-50 |

### Troubleshooting

| Issue | Fix |
| --- | --- |
| `containerlab: command not found` | Ensure install completed: `which containerlab`. Retry install script. |
| SR Linux image pull denied | Authenticate to GHCR: `docker login ghcr.io`. The image may be public -- retry without auth. |
| `error creating network namespace` | Must run with `sudo`. |
| Nodes start but links are down | Recreate: `sudo containerlab destroy ... && sudo containerlab deploy ...` |
| Not enough memory for 3 SR Linux nodes | Each node uses ~1GB RAM. Ensure at least 4GB free. |

### Cleanup

```bash
sudo containerlab destroy --topo containerlab/topology.clab.yml
```

---

## Step 7: Start Worker + Verify

**Purpose:** Start the Temporal worker and verify the complete platform works end-to-end.

### 7.1 Start the Worker

```bash
uv run invoke workers.start
```

The worker will connect to Temporal at localhost:7233 and register on the `network-changes`
task queue. Press `Ctrl+C` to stop.

### 7.2 Run Unit Tests

```bash
uv run invoke backend.test-unit
```

### 7.3 Run Integration Tests (if Containerlab deployed)

```bash
uv run invoke backend.test-integration
```

### Verification

```bash
# Unit tests pass
uv run invoke backend.test-unit 2>&1 | tail -3

# Config generation works end-to-end
uv run invoke backend.generate-configs --dry-run

# Worker is registered with Temporal
# Open http://localhost:8080 to see registered workers in Temporal UI
```

### Troubleshooting

| Issue | Fix |
| --- | --- |
| Worker can't connect to Temporal | Check: `TEMPORAL_ADDRESS=localhost:7233` in `.env`. Verify Temporal is running: `docker compose ps` |
| Tests fail with import errors | Re-run `uv sync --all-groups` |
| Tests fail with connection errors | Unit tests mock external services. If integration tests fail, check all services are running. |

---

## Step 8: Observability

**Purpose:** Grafana and Prometheus for monitoring.

Grafana and Prometheus are included in the 12-container stack started by `uv run invoke dev.deps`
(Step 4). No additional setup is needed.

| Service | URL | Credentials |
| --- | --- | --- |
| Grafana | http://localhost:3000 | admin / synapse |
| Prometheus | http://localhost:9090 | (no auth) |

---

## End-to-End Verification Checklist

Run this after all steps complete to verify the full platform:

```bash
echo "=== 1. Infrastructure Services ==="
docker compose -f development/docker-compose-deps.yml ps --format "table {{.Name}}\t{{.Status}}"

echo ""
echo "=== 2. Infrahub API ==="
curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:8000
echo ""

echo ""
echo "=== 3. Infrahub Data ==="
curl -s -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "{ DcimDevice { edges { node { hostname { value } } } } }"}' \
  | jq -r '.data.DcimDevice.edges[].node.hostname.value' 2>/dev/null

echo ""
echo "=== 4. Temporal UI ==="
curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:8080
echo ""

echo ""
echo "=== 5. Unit Tests ==="
uv run invoke backend.test-unit 2>&1 | tail -1

echo ""
echo "=== 6. Lint ==="
uv run invoke lint 2>&1 | tail -1

echo ""
echo "=== 7. Containerlab (if deployed) ==="
sudo containerlab inspect --topo containerlab/topology.clab.yml 2>/dev/null \
  | grep -c "running" || echo "Containerlab not deployed (Step 6)"

echo ""
echo "=== DONE ==="
```

---

## Quick Reference: Service URLs

All services are accessible on localhost:

| Service | URL | Default Credentials |
| --- | --- | --- |
| Infrahub UI | http://localhost:8000 | admin / infrahub |
| Temporal UI | http://localhost:8080 | (no auth) |
| Task Manager (Prefect) | http://localhost:4200 | (no auth) |
| Neo4j Browser | http://localhost:7474 | neo4j / infrahub |
| RabbitMQ Mgmt | http://localhost:15672 | guest / guest |
| Grafana | http://localhost:3000 | admin / synapse |
| Prometheus | http://localhost:9090 | (no auth) |
