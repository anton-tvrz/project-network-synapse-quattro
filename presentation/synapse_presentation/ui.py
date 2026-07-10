"""Minimal HTML UI for the self-service portal (ADR-0005).

Deliberately lightweight: one inline page, no build step, no external assets.
The API key is kept in the browser session only and sent as ``X-API-Key``.
"""

INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NSQuattro Self-Service</title>
<style>
  :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
  body { max-width: 60rem; margin: 2rem auto; padding: 0 1rem; }
  fieldset { margin-bottom: 1.5rem; border-radius: 6px; }
  label { display: block; margin: 0.5rem 0 0.15rem; font-size: 0.9rem; }
  input, select { width: 100%; max-width: 24rem; padding: 0.35rem; }
  button { margin-top: 0.75rem; padding: 0.4rem 1rem; cursor: pointer; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 0.35rem 0.6rem; border-bottom: 1px solid #8884; }
  #result { white-space: pre-wrap; font-family: monospace; margin-top: 1rem; }
</style>
</head>
<body>
<h1>NSQuattro Self-Service</h1>
<p>Actions start Temporal workflows through the Orchestrator; the initiator is recorded in workflow history.</p>

<fieldset>
  <legend>Credentials</legend>
  <label for="apikey">API key</label>
  <input id="apikey" type="password" autocomplete="off" placeholder="X-API-Key">
</fieldset>

<fieldset>
  <legend>Deploy device configuration</legend>
  <label for="dep-host">Device hostname</label>
  <input id="dep-host" placeholder="leaf01">
  <label for="dep-ip">IP address</label>
  <input id="dep-ip" placeholder="172.20.20.11">
  <button onclick="startDeployment()">Start deployment</button>
</fieldset>

<fieldset>
  <legend>Request operational override</legend>
  <label for="ov-name">Override name</label>
  <input id="ov-name" placeholder="maint-leaf01">
  <label for="ov-host">Device hostname</label>
  <input id="ov-host" placeholder="leaf01">
  <label for="ov-ip">IP address</label>
  <input id="ov-ip" placeholder="172.20.20.11">
  <label for="ov-type">Override type</label>
  <select id="ov-type">
    <option>maintenance_mode</option>
    <option>admin_shutdown</option>
    <option>traffic_drain</option>
    <option>emergency_bypass</option>
  </select>
  <label for="ov-config">Override config (SR Linux JSON)</label>
  <input id="ov-config" value="{}">
  <label for="ov-reason">Reason</label>
  <input id="ov-reason" placeholder="planned linecard swap">
  <label for="ov-duration">Duration (seconds)</label>
  <input id="ov-duration" type="number" value="600">
  <button onclick="startOverride()">Request override</button>
</fieldset>

<fieldset>
  <legend>Recent workflows</legend>
  <button onclick="refreshWorkflows()">Refresh</button>
  <table id="wf-table">
    <thead><tr><th>Workflow ID</th><th>Type</th><th>Status</th><th>Started</th></tr></thead>
    <tbody></tbody>
  </table>
</fieldset>

<div id="result"></div>

<script>
const val = (id) => document.getElementById(id).value;
const show = (obj) => { document.getElementById("result").textContent = JSON.stringify(obj, null, 2); };

async function call(method, path, body) {
  const response = await fetch(path, {
    method,
    headers: { "X-API-Key": val("apikey"), "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { show({ error: response.status, detail: data.detail }); throw new Error(response.status); }
  return data;
}

async function startDeployment() {
  show(await call("POST", "/api/deployments", { device_hostname: val("dep-host"), ip_address: val("dep-ip") }));
}

async function startOverride() {
  show(await call("POST", "/api/overrides", {
    override_name: val("ov-name"),
    device_hostname: val("ov-host"),
    ip_address: val("ov-ip"),
    override_type: val("ov-type"),
    override_config_json: val("ov-config"),
    reason: val("ov-reason"),
    duration_seconds: Number(val("ov-duration")),
  }));
}

async function refreshWorkflows() {
  const data = await call("GET", "/api/workflows");
  const tbody = document.querySelector("#wf-table tbody");
  tbody.replaceChildren(...data.workflows.map((wf) => {
    const row = document.createElement("tr");
    for (const field of [wf.workflow_id, wf.workflow_type, wf.status, wf.start_time]) {
      const cell = document.createElement("td");
      cell.textContent = field ?? "";
      row.appendChild(cell);
    }
    return row;
  }));
}
</script>
</body>
</html>
"""
