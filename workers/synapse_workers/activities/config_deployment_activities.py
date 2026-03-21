"""Temporal activities for deploying configurations to network devices."""

from temporalio import activity

from network_synapse.scripts.deploy_configs import deploy_config as push_via_gnmi

# TODO: Add device credential management (env vars or vault)
# For MVP, we will use Containerlab default SR Linux credentials
DEFAULT_USER = "admin"
DEFAULT_PASS = "NokiaSrl1!"  # noqa: S105


@activity.defn
async def deploy_config(device_hostname: str, ip_address: str, config_json: str) -> bool:
    """Deploy configuration to a network device via gNMI.

    Connects to the Containerlab SR Linux node and pushes the JSON structure.
    """
    activity.logger.info(f"Deploying config to {device_hostname} at {ip_address}")

    # We execute synchronous pygnmi in the activity threadpool
    result = push_via_gnmi(
        hostname=device_hostname,
        ip_address=ip_address,
        config_payload=config_json,
        username=DEFAULT_USER,
        password=DEFAULT_PASS,
    )

    if not result:
        raise RuntimeError(f"Config deployment failed for {device_hostname}")

    return True


@activity.defn
async def rollback_config(device_hostname: str, ip_address: str, backup_config_json: str) -> bool:
    """Rollback device to previous configuration.

    Applies the backup JSON configuration via gNMI SET.
    """
    activity.logger.info(f"Rolling back config for {device_hostname} to previous state")

    result = push_via_gnmi(
        hostname=device_hostname,
        ip_address=ip_address,
        config_payload=backup_config_json,
        username=DEFAULT_USER,
        password=DEFAULT_PASS,
    )

    if not result:
        raise RuntimeError(f"Rollback failed for {device_hostname}. Device may be in an inconsistent state!")

    return True
