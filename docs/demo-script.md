# Network Synapse Quattro -- Demo Script

> **Target duration:** Under 10 minutes
> **Prerequisites:** Infrastructure running locally, Containerlab deployed, Infrahub seeded, Temporal worker active

---

## 1. Show Infrahub Source of Truth (1 min)

1. Open Infrahub UI: `http://localhost:8000`
2. Navigate to **Devices** -- show the 3-node spine-leaf topology
3. Click into **spine01** -- show hostname, ASN (65000), management IP, interfaces
4. Highlight the **BGP Sessions** relationship -- show eBGP peering to leaf01/leaf02

> **Key point:** "All network intent lives here. No spreadsheets, no CLI."

---

## 2. Trigger a Configuration Change (1 min)

1. In Infrahub, add a new BGP neighbor to **spine01**:
   - Peer address: `10.0.99.1`
   - Remote AS: `65099`
   - Group: `EXTERNAL`
2. Save the change -- show the audit trail in Infrahub

> **Key point:** "Change intent first, then automate the deployment."

---

## 3. Show Config Generation (2 min)

1. Run the config generator from the terminal:
   ```bash
   uv run python -m network_synapse.scripts.generate_configs
   ```
2. Show the generated SR Linux JSON output
3. Highlight the YANG-modeled structure (not CLI commands)

> **Key point:** "Jinja2 templates produce gNMI-ready JSON, not SSH commands."

---

## 4. Show the Temporal Workflow (2 min)

1. Open Temporal UI: `http://localhost:8080`
2. Trigger the `NetworkChangeWorkflow`:

   ```bash
   uv run python -c "
   import asyncio
   from temporalio.client import Client

   async def main():
       client = await Client.connect('localhost:7233')
       result = await client.execute_workflow(
           'NetworkChangeWorkflow',
           args=['spine01', '172.20.20.10'],
           id='demo-deploy',
           task_queue='network-synapse'
       )
       print(f'Result: {result}')

   asyncio.run(main())
   "
   ```

3. In the Temporal UI, show the workflow execution:
   - **Step 1:** Backup (gNMI GET)
   - **Step 2:** Fetch intention (Infrahub GraphQL)
   - **Step 3:** Generate config (Jinja2)
   - **Step 4:** Hygiene check (pre-deployment gate)
   - **Step 5:** Deploy (gNMI SET)
   - **Step 6:** Validate BGP (gNMI GET operational state)
   - **Step 7:** Update status in Infrahub

> **Key point:** "Every step is auditable, retryable, and has automatic rollback."

---

## 5. Show Post-Deployment Validation (1 min)

1. Use gNMI to show BGP state:
   ```bash
   uv run python -c "
   from network_synapse.scripts.validate_state import check_bgp_summary
   print('BGP OK:', check_bgp_summary('172.20.20.10'))
   "
   ```
2. Show all BGP sessions as `ESTABLISHED`

> **Key point:** "We validate what we deploy. If BGP doesn't come up, we auto-rollback."

---

## 6. Show Grafana Dashboards (2 min)

1. Open Grafana: `http://localhost:3000` (admin/synapse)
2. Walk through each dashboard:
   - **System Health** -- CPU, memory, disk, network
   - **Network Operations** -- BGP sessions, interface states, route counts
   - **Automation Pipeline** -- Temporal workflow success rates, durations
   - **Compliance Tracking** -- Hygiene check pass rates, drift scores
   - **Capacity Planning** -- Resource trends, growth projections

> **Key point:** "Full observability from infrastructure to application."

---

## 7. Show Rollback on Failure (1 min)

1. Explain the rollback flow in the Temporal UI
2. Show a failed workflow where:
   - Deployment succeeded but BGP validation failed
   - The workflow automatically rolled back the config
   - Infrahub status was updated to "failed"

> **Key point:** "Failures are handled gracefully. No manual intervention needed."

---

## Summary Talking Points

- **Source of Truth:** Infrahub stores all network intent
- **Orchestration:** Temporal provides durable, auditable workflows
- **Deployment:** gNMI for programmatic config push (not SSH)
- **Validation:** Pre-deployment hygiene + post-deployment BGP checks
- **Observability:** Prometheus + Grafana for metrics, Suzieq for network state
- **Safety:** Automatic rollback on any failure
