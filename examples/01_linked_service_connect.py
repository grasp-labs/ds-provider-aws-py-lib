"""
**File:** ``01_linked_service_connect.py``
**Region:** ``examples/01_linked_service_connect``

Example 01: Connect to AWS with boto3 using a linked service.

This example demonstrates how to:
- Create a AWS linked service
- Creates a connection using boto3
- Test the connection
"""

from __future__ import annotations

from ds_common_logger_py_lib import Logger
from ds_resource_plugin_py_lib.common.resource.errors import ResourceException

from ds_provider_aws_py_lib.linked_service.aws import (
    AWSLinkedService,
    AWSLinkedServiceSettings,
)

logger = Logger.get_logger(__name__, package=True)


def main() -> None:
    """Main function demonstrating AWS linked service connection."""
    linked_service = AWSLinkedService(
        settings=AWSLinkedServiceSettings(
            account_id="your_account_id",
            access_key_id="your_access_key_id",
            access_key_secret="your_access_key_secret",
            region="us-west-2",
        ),
    )

    try:
        logger.debug("Connecting to AWS...")
        linked_service.connect()

        logger.debug("Testing connection...")
        success, message = linked_service.test_connection()
        if success:
            logger.debug("Connection test successful: %s", message)
        else:
            raise ResourceException(message=message)
    except ResourceException as exc:
        logger.error("Failed to connect to AWS: %s", exc.message)
        raise
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        raise


if __name__ == "__main__":
    main()
