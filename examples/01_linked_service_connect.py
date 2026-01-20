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

Logger()
logger = Logger.get_logger(__name__)


def main() -> None:
    """Main function demonstrating PostgreSQL linked service connection."""
    linked_service = AWSLinkedService(
        settings=AWSLinkedServiceSettings(
            access_key_id="your_access_key_id",
            access_key_secret="your_access_key_secret",
            region="us-west-2",
        ),
    )

    try:
        logger.info("Connecting to AWS...")
        linked_service.connect()

        logger.info("Testing connection...")
        success, message = linked_service.test_connection()
        if success:
            logger.info(f"Connection test successful: {message}")
        else:
            raise ResourceException(message=message)
    except ResourceException as exc:
        logger.error(f"Failed to connect to AWS: {exc.message}")
        raise
    except Exception as exc:
        logger.error(f"Unexpected error: {exc!s}")
        raise


if __name__ == "__main__":
    main()
