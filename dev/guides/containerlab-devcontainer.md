# Containerlab on OrbStack (Docker-Outside-Of-Docker)

To allow our local development containers (like `synapse-worker` and `infrahub-server`) to communicate directly with our virtual network switches natively without complex routing, we use **Containerlab in a Docker container** (specifically, the Docker-Outside-Of-Docker or DooD approach).

## Architecture

```text
macOS Host
└── OrbStack Docker Engine
    ├── Infrahub Server
    ├── Temporal Worker
    ├── [ ... other containers ... ]
    ├── clab-spine-leaf-lab-spine01 (Nokia SR Linux)
    ├── clab-spine-leaf-lab-leaf01  (Nokia SR Linux)
    └── clab-spine-leaf-lab-leaf02  (Nokia SR Linux)
```

*Notice that all components share the same Docker Engine!*

## Lifecycle Management

We have wrapped the Containerlab CLI in our `invoke` tasks, so you do not need to install Containerlab on macOS. It will pull the official `ghcr.io/srl-labs/clab` docker image and mount your Docker socket.

```bash
# Deploy the lab
uv run invoke dev.lab-deploy

# Destroy the lab
uv run invoke dev.lab-destroy
```

Alternatively, if you use VS Code, you can use the "**Reopen in Container**" feature with the provided `.devcontainer/devcontainer.json` to get a terminal with the `containerlab` binary natively available.

## Access Information

### From macOS Terminal
Because macOS does not route custom Docker bridge IP addresses natively, you should interact with the switches using Docker's native `exec` command to drop directly into the Nokia SR Linux CLI (`sr_cli`):

```bash
docker exec -it clab-spine-leaf-lab-spine01 sr_cli
docker exec -it clab-spine-leaf-lab-leaf01 sr_cli
```
*(No password needed!)*

### From Local Docker Containers (like Python Workers)

Any container that needs to talk to the switches can do so. For example, if your Temporal worker runs in the `development_default` network, you can bridge it to the `clab` network:

```bash
docker network connect clab development_synapse-worker_1
```

Then, the worker can reach the switch via DNS:
`clab-spine-leaf-lab-spine01`
