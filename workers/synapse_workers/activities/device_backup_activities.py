"""Temporal activities for backing up device configurations."""

import json

from pygnmi.client import gNMIclient
from temporalio import activity


@activity.defn
async def backup_running_config(
    device_hostname: str,
    ip_address: str,
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
) -> str:
    """Backup the current running configuration from a device via gNMI GET.

    Returns config as JSON string.
    """
    activity.logger.info(f"Backing up config for {device_hostname} at {ip_address}")

    try:
        with gNMIclient(target=(ip_address, 57400), username=username, password=password, insecure=True) as gc:
            # Issue a GET request for the root path
            result = gc.get(path=["/"])

            # The payload is nestled inside the protobuf response dictionary
            if "notification" in result and len(result["notification"]) > 0:
                for notif in result["notification"]:
                    if "update" in notif and len(notif["update"]) > 0:
                        for update in notif["update"]:
                            if "val" in update:
                                # Return the raw JSON dictionary dumped to a string
                                return json.dumps(update["val"])

            raise RuntimeError(f"Unexpected gNMI GET format from {device_hostname}: {result}")

    except Exception as e:
        activity.logger.error(f"Failed to backup {device_hostname}: {e!s}")
        raise RuntimeError(f"Backup failed: {e!s}") from e


@activity.defn
async def store_backup(device_hostname: str, config: str) -> None:
    """Store a configuration backup.

    For the MVP, we just log it. A real system would write to S3 or git.
    """
    activity.logger.info(f"Stored backup for {device_hostname} ({len(config)} bytes)")
    # TODO: Implement actual persistent storage write
