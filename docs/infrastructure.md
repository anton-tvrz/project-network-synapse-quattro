# Infrastructure Connection Guide

This document covers how to connect to all services running locally on macOS with OrbStack.

## Local Environment

| Property | Value |
|----------|-------|
| **Machine** | MacBook M5, 32GB RAM |
| **Container Runtime** | OrbStack |
| **Branch** | `main` |
| **Services** | Infrahub (7 containers), Temporal (3 containers), Observability (2 containers), Containerlab, synapse-worker |

All services run locally. No SSH tunnels, no cloud VMs, no remote access needed.

---

## Containerlab (Nokia SR Linux)

### Topology

Spine-leaf topology with 1 spine and 2 leaf switches, all Nokia SR Linux.

| Device | Role | Type | Management IP | Container Name |
|--------|------|------|---------------|----------------|
| spine01 | spine | 7220 IXR-D3 | 172.20.20.3 | clab-spine-leaf-lab-spine01 |
| leaf01 | leaf | 7220 IXR-D2 | 172.20.20.2 | clab-spine-leaf-lab-leaf01 |
| leaf02 | leaf | 7220 IXR-D2 | 172.20.20.4 | clab-spine-leaf-lab-leaf02 |

### Credentials

| Protocol | Username | Password |
|----------|----------|----------|
| SSH / JSON-RPC / gNMI | `admin` | `NokiaSrl1!` |

### Connecting to Devices

With OrbStack, the `172.20.20.x` management network is directly accessible from macOS.
No tunnels or proxy setup required.

```bash
# SSH into a device (directly from macOS terminal)
ssh admin@172.20.20.3          # spine01
ssh admin@172.20.20.2          # leaf01
ssh admin@172.20.20.4          # leaf02
```

### JSON-RPC (HTTPS, port 443)

```bash
curl -sk https://172.20.20.3/jsonrpc -u admin:NokiaSrl1! \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "get",
    "params": {
      "commands": [
        {"path": "/system/information"}
      ]
    }
  }'
```

### gNMI (port 57400)

```bash
# Using pygnmi or similar
# Target: 172.20.20.3:57400 (spine01)
# TLS: insecure (self-signed cert)
```

### Containerlab CLI

```bash
# Inspect running topology
sudo containerlab inspect -t containerlab/topology.clab.yml

# Interactive topology graph (web UI on port 50080)
sudo containerlab graph -t containerlab/topology.clab.yml

# Destroy and redeploy
sudo containerlab destroy -t containerlab/topology.clab.yml
sudo containerlab deploy -t containerlab/topology.clab.yml
```

### Topology Diagram

```
             +----------+
             |  spine01  |
             | IXR-D3   |
             | .3       |
             +-+--+-+--++
          e1-1 |  | |  | e1-4
               |  | |  |
          e1-49|  | |  |e1-49
             +-+--+ +--+-+
             |            |
         +---+---+   +---+---+
         | leaf01 |   | leaf02 |
         | IXR-D2 |   | IXR-D2 |
         | .2     |   | .4     |
         +--------+   +--------+

Links:
  spine01:e1-1 <-> leaf01:e1-49
  spine01:e1-2 <-> leaf02:e1-49
  spine01:e1-3 <-> leaf01:e1-50
  spine01:e1-4 <-> leaf02:e1-50

Management: 172.20.20.0/24
```

---

## Infrahub (Source of Truth)

### Connection Details

| Interface | URL | Notes |
|-----------|-----|-------|
| Web UI | http://localhost:8000 | Direct access |
| GraphQL Playground | http://localhost:8000/graphql | Interactive query editor |
| REST API | http://localhost:8000/api/ | Schema management |

### Credentials

| Username | Password |
|----------|----------|
| `admin` | `infrahub` |

### Accessing the UI

```bash
open http://localhost:8000
```

### GraphQL API

```bash
# Get an auth token
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "infrahub"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Query all devices
curl -s -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "{ DcimDevice { edges { node { display_label management_ip { value } role { value } } } } }"
  }' | python3 -m json.tool

# Query BGP sessions
curl -s -X POST http://localhost:8000/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "query": "{ RoutingBGPSession { edges { node { display_label description { value } session_type { value } } } } }"
  }' | python3 -m json.tool
```

### Python SDK

```python
from infrahub_sdk import InfrahubClient

async def main():
    client = await InfrahubClient.init(
        address="http://localhost:8000",
        # token="<optional-api-token>"
    )

    # Query devices
    devices = await client.all("DcimDevice")
    for device in devices:
        print(f"{device.name.value} - {device.management_ip.value}")
```

### Loaded Schemas

The following schema extensions are loaded (in dependency order):

1. **Base schemas** (pre-loaded): DcimDevice, InterfacePhysical, IpamIPAddress, LocationSite, etc.
2. **VRF extension**: IpamVRF, IpamRouteTarget
3. **Routing base**: RoutingProtocol (generic)
4. **Routing BGP**: RoutingAutonomousSystem, RoutingBGPPeerGroup, RoutingBGPSession
5. **Custom device extension**: management_ip, lab_node_name, asn (on DcimDevice)
6. **Custom interface extension**: role dropdown (on InterfacePhysical)

See [schemas.md](schemas.md) for full schema architecture details.

### Seed Data

The Infrahub instance is pre-populated with:

| Object Type | Count | Details |
|-------------|-------|---------|
| Devices | 3 | spine01, leaf01, leaf02 |
| Interfaces | 11 | 4x spine fabric + loopback, 2x per leaf fabric + loopback |
| IP Addresses | 11 | /31 fabric links + /32 loopbacks |
| Autonomous Systems | 3 | AS65000 (spine), AS65001 (leaf01), AS65002 (leaf02) |
| BGP Sessions | 4 | eBGP underlay on all fabric links |
| VRFs | 1 | default |

See [seed-data.md](seed-data.md) for the full IP addressing plan.

### Docker Containers (Infrahub Stack -- 7 containers)

The Infrahub stack consists of 7 containers:

| Container | Role | Port |
|-----------|------|------|
| infrahub-database (neo4j) | Graph database | 7474, 7687 |
| infrahub-cache (redis) | Cache layer | 6379 |
| infrahub-message-queue (rabbitmq) | Message broker | 5672, 15672 |
| task-manager-db (postgres) | Task manager persistence | 5433 |
| task-manager | Prefect-based task orchestration | 4200 |
| infrahub-server | Infrahub API + UI | 8000 |
| task-worker | Background task processor | -- |

The default admin API token (`06438eb2-8019-4776-878c-0941b1f1d1ec`) is pre-configured.
No manual token creation via the UI is needed.

```bash
# Check Infrahub container status
docker ps --filter "name=infrahub"

# View logs
docker compose -f development/docker-compose-deps.yml logs -f infrahub-server

# Restart
docker compose -f development/docker-compose-deps.yml restart infrahub-server

# Task Manager (Prefect API)
curl http://localhost:4200/api/health
```

> **Note:** Infrahub takes 60-90s to fully initialize (Neo4j + task-manager must be ready first).
> SuzieQ is commented out in docker-compose (broken on Apple Silicon).

---

## Temporal (Workflow Orchestration)

### Connection Details

| Interface | URL / Address | Notes |
|-----------|---------------|-------|
| Web UI | http://localhost:8080 | Direct access |
| gRPC | localhost:7233 | Worker/client connections |
| Namespace | `default` | Primary namespace |
| Task Queue | `network-changes` | Project task queue |

### Accessing the UI

```bash
open http://localhost:8080
```

### Python SDK

```python
import asyncio
from datetime import timedelta

from temporalio.client import Client
from temporalio.worker import Worker

async def main():
    # Connect to Temporal
    client = await Client.connect("localhost:7233")

    # Execute a workflow
    result = await client.execute_workflow(
        "MyWorkflow",
        id="my-workflow-id",
        task_queue="network-changes",
    )
    print(f"Result: {result}")
```

### Environment Variable

The worker reads the Temporal address from an environment variable:

```bash
export TEMPORAL_ADDRESS="localhost:7233"  # default
```

### Docker Containers (Temporal Stack -- 3 containers)

| Container | Role | Port |
|-----------|------|------|
| temporal-db (postgres) | Temporal persistence | 5432 |
| temporal | Workflow engine | 7233 |
| temporal-ui | Web dashboard | 8080 |

```bash
# Check Temporal container status
docker ps --filter "name=temporal"

# View logs
docker compose -f development/docker-compose-deps.yml logs -f temporal

# Temporal CLI (via admin-tools container)
docker exec temporal temporal operator namespace list
docker exec temporal temporal operator cluster health
```

---

## Observability (2 containers)

Prometheus and Grafana are included in the docker-compose stack started by `uv run invoke dev.deps`.

| Service | URL | Credentials |
|---------|-----|-------------|
| Prometheus | http://localhost:9090 | (no auth) |
| Grafana | http://localhost:3000 | admin / synapse |

```bash
# Check observability containers
docker ps --filter "name=prometheus"
docker ps --filter "name=grafana"
```

---

## Container Summary

All 12 containers are started by `uv run invoke dev.deps` (~10GB total memory reserved):

| Stack | Containers | Count |
|-------|-----------|-------|
| Infrahub | neo4j, redis, rabbitmq, task-manager-db (postgres), task-manager, infrahub-server, task-worker | 7 |
| Temporal | postgres, temporal, temporal-ui | 3 |
| Observability | prometheus, grafana | 2 |
| **Total** | | **12** |

---

## Port Reference

All services listen on `localhost` and are directly accessible from macOS.
OrbStack container IPs (172.20.20.x) are also directly routable from the host.

| Port | Service | Protocol | Access |
|------|---------|----------|--------|
| 8000 | Infrahub Web UI + API | HTTP | http://localhost:8000 |
| 8080 | Temporal Web UI | HTTP | http://localhost:8080 |
| 7233 | Temporal gRPC | gRPC | localhost:7233 |
| 4200 | Task Manager (Prefect API) | HTTP | http://localhost:4200 |
| 3000 | Grafana | HTTP | http://localhost:3000 |
| 9090 | Prometheus | HTTP | http://localhost:9090 |
| 443 | SR Linux JSON-RPC (per device) | HTTPS | https://172.20.20.x |
| 57400 | SR Linux gNMI (per device) | gRPC/TLS | 172.20.20.x:57400 |
| 50080 | Containerlab Graph UI | HTTP | http://localhost:50080 |
| 6379 | Redis (Infrahub cache) | TCP | localhost:6379 |
| 7474 | Neo4j Browser | HTTP | http://localhost:7474 |
| 7687 | Neo4j Bolt | Bolt | localhost:7687 |
| 5432 | PostgreSQL (Temporal) | TCP | localhost:5432 |
| 5433 | PostgreSQL (Task Manager) | TCP | localhost:5433 |
| 15672 | RabbitMQ Management | HTTP | http://localhost:15672 |

---

## Troubleshooting

### Services not starting

```bash
# Check all containers
docker ps -a

# Check container logs
docker compose -f development/docker-compose-deps.yml logs -f
```

### Containerlab nodes not reachable

```bash
# Verify nodes are running
sudo containerlab inspect -t containerlab/topology.clab.yml

# Check docker networks
docker network ls | grep clab

# Ping from macOS (OrbStack makes this work directly)
ping -c 2 172.20.20.3
```

### Port conflict

```bash
# Check what is using a port
lsof -i :8000

# Override port in .env if needed
```

### Infrahub API returns 401

```bash
# Re-authenticate (tokens expire after 1 hour)
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "infrahub"}'
```
