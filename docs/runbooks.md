# Operational Runbooks

## Table of Contents

1. [Adding a New Device](#1-adding-a-new-device)
2. [Troubleshooting Failed Temporal Workflows](#2-troubleshooting-failed-temporal-workflows)
3. [Handling Drift Detection Alerts](#3-handling-drift-detection-alerts)
4. [Emergency Rollback Procedure](#4-emergency-rollback-procedure)
5. [Infrahub / Temporal Disaster Recovery](#5-infrahub--temporal-disaster-recovery)
6. [Break-Glass Container Access](#6-break-glass-container-access)

---

## 1. Adding a New Device

**When:** A new SR Linux node is added to the fabric (e.g., leaf03).

### Steps

1. **Add to Infrahub:**
   - Create the `NetworkDevice` object with hostname, ASN, management IP, role
   - Create `NetworkInterface` objects for each fabric-facing port
   - Create `BGPSession` objects for eBGP peering to spines

2. **Add to Containerlab topology:**

   ```yaml
   # containerlab/topology.clab.yml
   leaf03:
     kind: nokia_srlinux
     image: ghcr.io/nokia/srlinux:latest
     mgmt-ipv4: 172.20.20.13
   ```

3. **Add to Suzieq inventory:**

   ```yaml
   # development/suzieq/suzieq-inventory.yml
   - hostname: leaf03
     address: 172.20.20.13
   ```

4. **Add to Prometheus:**

   ```yaml
   # development/prometheus/prometheus.yml
   - targets: ["172.20.20.13:57400"]
   ```

5. **Deploy topology:**

   ```bash
   sudo containerlab deploy -t containerlab/topology.clab.yml
   ```

6. **Run the Temporal workflow:**
   ```bash
   # Trigger NetworkChangeWorkflow for the new device
   uv run python -c "..." # See demo-script.md
   ```

---

## 2. Troubleshooting Failed Temporal Workflows

**When:** A `NetworkChangeWorkflow` fails.

### Steps

1. **Check Temporal UI:** http://localhost:8080
   - Find the failed workflow by ID
   - Check which activity failed (backup, deploy, validate, etc.)
   - Read the error message in the activity output

2. **Common failure reasons:**

   | Activity | Likely Cause | Fix |
   | --- | --- | --- |
   | `backup_running_config` | Device unreachable | Check gNMI connectivity, verify IP/port |
   | `fetch_device_config` | Infrahub down | Check `docker compose ps`, restart if needed |
   | `deploy_config` | Invalid JSON payload | Run hygiene checker locally, fix templates |
   | `validate_bgp` | BGP not converging | Wait for convergence, check peer config |

3. **Retry the workflow:**
   - In Temporal UI, click "Reset" on the failed workflow
   - Or trigger a new execution from the CLI

4. **If rollback occurred:** Check Infrahub -- the device status should be marked "failed". Fix the root cause, then re-run.

---

## 3. Handling Drift Detection Alerts

**When:** Suzieq or Prometheus detects config drift on a device.

### Steps

1. **Identify the drift:**
   - Check Grafana **Compliance Tracking** dashboard
   - Check Suzieq REST API: `http://localhost:8530/api/v2/device?view=latest`

2. **Determine if intentional:**
   - Was there a recent manual change on the device?
   - Was there an out-of-band configuration update?

3. **Remediate:**
   - If **unintentional**: Re-run the `NetworkChangeWorkflow` to push the correct intent from Infrahub
   - If **intentional**: Update Infrahub to match the new desired state, then re-run the workflow

---

## 4. Emergency Rollback Procedure

**When:** A deployment caused an outage and you need to restore the previous config immediately.

### Steps

1. **Automatic rollback:** The `NetworkChangeWorkflow` already handles this. If deployment or validation fails, the backup config is automatically restored via gNMI SET.

2. **Manual rollback (if Temporal is down):**

   ```bash
   # Find the latest backup
   ls -la /tmp/backups/<device_hostname>/

   # Push the backup config directly via gNMI
   uv run python -c "
   from network_synapse.scripts.deploy_configs import deploy_config
   import json

   with open('/tmp/backups/spine01/latest.json') as f:
       backup = f.read()

   deploy_config('spine01', '172.20.20.10', backup)
   "
   ```

3. **Verify recovery:**
   ```bash
   uv run python -c "
   from network_synapse.scripts.validate_state import check_bgp_summary
   print('BGP OK:', check_bgp_summary('172.20.20.10'))
   "
   ```

---

## 5. Infrahub / Temporal Disaster Recovery

**When:** A core service is down and won't restart.

### Infrahub Recovery

```bash
# Check status
docker compose -f development/docker-compose-deps.yml ps

# Restart Infrahub stack
docker compose -f development/docker-compose-deps.yml restart infrahub-server infrahub-database infrahub-cache

# If data is corrupted, restore from Neo4j backup
docker compose -f development/docker-compose-deps.yml down infrahub-database
docker volume rm development_neo4j_data
docker compose -f development/docker-compose-deps.yml up -d infrahub-database
# Re-seed: uv run invoke backend.load-schemas && uv run invoke backend.seed-data
```

### Temporal Recovery

```bash
# Restart Temporal
docker compose -f development/docker-compose-deps.yml restart temporal temporal-ui

# If SQLite DB is corrupted
docker compose -f development/docker-compose-deps.yml down temporal
docker volume rm development_temporal_data
docker compose -f development/docker-compose-deps.yml up -d temporal
```

---

## 6. Break-Glass Container Access

**When:** All automation is down and you need emergency CLI access to a device.

### Steps

1. **Access SR Linux CLI via docker exec:**

   ```bash
   docker exec -it clab-spine-leaf-lab-spine01 sr_cli    # spine01
   docker exec -it clab-spine-leaf-lab-leaf01 sr_cli     # leaf01
   docker exec -it clab-spine-leaf-lab-leaf02 sr_cli     # leaf02
   # Linux Testing Clients
   docker exec -it clab-spine-leaf-lab-client1 /bin/bash # client1
   ```

2. **Alternatively, SSH directly (OrbStack makes 172.20.20.x reachable):**

   ```bash
   ssh admin@172.20.20.3  # spine01
   ssh admin@172.20.20.2  # leaf01
   ssh admin@172.20.20.4  # leaf02
   # Password: NokiaSrl1!
   ```

3. **Useful SR Linux commands:**
   ```
   show network-instance default protocols bgp neighbor
   show interface brief
   show network-instance default route-table
   show system information
   ```

> **IMPORTANT:** Document any manual changes made during break-glass access. Update Infrahub afterwards to ensure the source of truth reflects reality.
