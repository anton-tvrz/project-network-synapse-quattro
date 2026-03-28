# Containerlab — Virtual Network Lab Skill

## Metadata
- name: containerlab
- triggers: containerlab, clab, lab, topology, SR Linux image, OrbStack
- project: Network Synapse Quattro

## What is Containerlab?

Containerlab deploys container-based network topologies. NSQuattro uses it to run Nokia SR Linux switches locally on macOS via OrbStack (Docker).

## Topology YAML Structure

Topologies are defined in `containerlab/topologies/`:

```yaml
name: spine-leaf-lab
topology:
  kinds:
    nokia_srlinux:
      image: ghcr.io/nokia/srlinux:latest
  nodes:
    spine01:
      kind: nokia_srlinux
      type: ixr-d3
    leaf01:
      kind: nokia_srlinux
      type: ixr-d2
    leaf02:
      kind: nokia_srlinux
      type: ixr-d2
    firewall:
      kind: linux
      image: vyos/vyos:1.4-rolling-20240101
      memory: 1GB
    pc1:
      kind: linux
      image: wbitt/network-multitool:alpine-extra
    pc2:
      kind: linux
      image: wbitt/network-multitool:alpine-extra
  links:
    - endpoints: ["spine01:e1-1", "leaf01:e1-49"]
    - endpoints: ["spine01:e1-2", "leaf02:e1-49"]
    - endpoints: ["spine01:e1-3", "leaf01:e1-50"]
    - endpoints: ["spine01:e1-4", "leaf02:e1-50"]
    - endpoints: ["pc1:eth1", "leaf01:e1-1"]
    - endpoints: ["firewall:eth1", "leaf02:e1-1"]
    - endpoints: ["firewall:eth2", "pc2:eth1"]
```

## Lab Lifecycle Commands

```bash
# Deploy lab
uv run invoke dev.lab-deploy

# Destroy lab
uv run invoke dev.lab-destroy

# Direct containerlab commands (if needed)
sudo containerlab deploy -t containerlab/topology.clab.yml
sudo containerlab destroy -t containerlab/topology.clab.yml
```

## Node Access

```bash
# Nokia SR Linux CLI
docker exec -it clab-spine-leaf-lab-spine01 sr_cli

# VyOS firewall
docker exec -it clab-spine-leaf-lab-firewall /bin/bash

# Alpine clients
docker exec -it clab-spine-leaf-lab-pc1 /bin/sh
docker exec -it clab-spine-leaf-lab-pc2 /bin/sh

# DNS names (from macOS)
clab-spine-leaf-lab-spine01
clab-spine-leaf-lab-leaf01
clab-spine-leaf-lab-leaf02
clab-spine-leaf-lab-firewall
clab-spine-leaf-lab-pc1
clab-spine-leaf-lab-pc2
```

## Management Network

- Network: `172.20.20.0/24`
- DHCP assigned by Containerlab
- Access from macOS host via OrbStack network bridge
- gNMI ports: spine01=57400, leaf01=57401, leaf02=57402

## OrbStack-Specific Notes (macOS)

- OrbStack provides Docker runtime on Apple Silicon
- Container DNS resolution works from macOS host
- No need for port forwarding — direct container network access
- Memory: allocate at least 10GB for full stack (Infrahub + Temporal + lab)

## Available Topologies

| File | Nodes | Use Case |
|------|-------|----------|
| `small.clab.yml` | 3 (1 spine, 2 leaf) | Default development |
| `medium.clab.yml` | 5 (2 spine, 3 leaf) | Multi-path testing |
| `large.clab.yml` | 8 (2 spine, 4 leaf, 2 border) | Scale testing |
| `border-leaf.clab.yml` | Adds border-leaf role | WAN edge simulation |

## Integration Testing

When writing integration tests that interact with lab devices:
1. Check lab is running: `docker ps | grep clab`
2. Use DNS names, not hardcoded IPs
3. Allow 30s warm-up after deploy for BGP convergence
4. Clean up any config changes in test teardown

## Common Mistakes

- Hardcoding management IPs (use DNS names)
- Not waiting for BGP convergence after lab deploy
- Missing OrbStack routing setup
- Trying to use `localhost` instead of container DNS names
