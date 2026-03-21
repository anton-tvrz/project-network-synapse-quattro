import json
import logging

from pygnmi.client import gNMIclient

# Configure logging
logger = logging.getLogger(__name__)


def deploy_config(
    hostname: str,
    ip_address: str,
    config_payload: str,
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
    port: int = 57400,
) -> bool:
    """Deploy a JSON configuration to a Nokia SR Linux device via gNMI."""
    logger.info(f"Deploying configuration to {hostname} ({ip_address}:{port})")

    try:
        try:
            config_dict = json.loads(config_payload)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse config payload as JSON for {hostname}: {e!s}")
            return False

        host = (ip_address, port)

        with gNMIclient(target=host, username=username, password=password, insecure=True) as gc:
            logger.debug(f"Successfully connected to gNMI on {hostname}")
            update_req = [("/", config_dict)]
            result = gc.set(update=update_req)
            logger.info(f"gNMI SET response for {hostname}: {result}")

            if result.get("response"):
                logger.info(f"Configuration successfully deployed to {hostname}")
                return True
            logger.error(f"Unexpected gNMI response from {hostname}: {result}")
            return False

    except Exception as e:
        logger.error(f"Failed to deploy configuration to {hostname}: {e!s}")
        return False


def validate_gnmi_connection(
    ip_address: str,
    username: str = "admin",
    password: str = "NokiaSrl1!",  # noqa: S107
    port: int = 57400,
) -> bool:
    """Test connectivity to a device without pushing config."""
    try:
        with gNMIclient(target=(ip_address, port), username=username, password=password, insecure=True) as gc:
            result = gc.capabilities()
            if result:
                return True
    except Exception as e:
        logger.error(f"Connection validation failed for {ip_address}: {e!s}")

    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Use this module by importing deploy_config")
