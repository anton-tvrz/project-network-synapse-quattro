# Running the Synapse Worker & Triggering Workflows

Step-by-step guide to start the Temporal worker and execute a network change workflow.

---

## Prerequisites

- Infrastructure containers running (`uv run invoke dev.deps`)
- Infrahub seeded with schemas + device data (see [install guide](install.md))
- Containerlab SR Linux nodes running (for end-to-end workflows)

---

## Step 1: Set Environment Variables

Ensure your `.env` file contains the required values:

```bash
TEMPORAL_ADDRESS="localhost:7233"
INFRAHUB_URL="http://localhost:8000"
INFRAHUB_TOKEN=""  # Set this after getting a token from Infrahub UI
```

---

## Step 2: Start the Synapse Worker

```bash
# Start the worker (foreground, recommended for development)
uv run invoke workers.start
```

You should see:
`Worker connected to localhost:7233, listening on queue 'network-changes'`

Press `Ctrl+C` to stop the worker.

---

## Step 3: Verify Worker in Temporal UI

1. Open Temporal UI: http://localhost:8080
2. Navigate to **Workers** -> **network-changes** task queue
3. You should see 1 active worker with 3 registered workflows:
   - `NetworkChangeWorkflow`
   - `DriftRemediationWorkflow`
   - `EmergencyChangeWorkflow`

---

## Step 4: Trigger a Test Workflow

```bash
uv run python -c "
import asyncio
from temporalio.client import Client

async def main():
    client = await Client.connect('localhost:7233')
    result = await client.execute_workflow(
        'NetworkChangeWorkflow',
        args=['spine01', '172.20.20.10'],
        id='demo-network-change-001',
        task_queue='network-changes',
    )
    print(f'Workflow result: {result}')

asyncio.run(main())
"
```

---

## Step 5: Watch the Workflow Execute

1. Open Temporal UI: http://localhost:8080
2. Click on workflow `demo-network-change-001`
3. Watch the 7 steps execute in real time:
   - Step 1: Backup running config (gNMI GET)
   - Step 2: Fetch intended config (Infrahub GraphQL)
   - Step 3: Generate SR Linux JSON
   - Step 4: Hygiene check (pre-deployment gate)
   - Step 5: Deploy config (gNMI SET)
   - Step 6: Validate BGP (gNMI GET operational state)
   - Step 7: Update device status in Infrahub

---

## Troubleshooting

| Issue | Fix |
| --- | --- |
| Worker can't connect to Temporal | Check `TEMPORAL_ADDRESS`. Verify Temporal is running: `docker ps \| grep temporal` |
| `fetch_device_config` fails | Set `INFRAHUB_URL` and `INFRAHUB_TOKEN`. Check Infrahub is healthy: `curl http://localhost:8000` |
| `backup_running_config` fails | Check Containerlab nodes are running: `sudo containerlab inspect` |
| `deploy_config` times out | Verify gNMI port 57400 is accessible on the SR Linux node |
| BGP validation fails | BGP may not be configured yet. Check: `docker exec clab-spine-leaf-lab-spine01 sr_cli "show network-instance default protocols bgp neighbor"` |

---

## Stopping the Worker

```bash
# If running in foreground: Ctrl+C

# If running in background:
pkill -f "synapse_workers.worker"
```
