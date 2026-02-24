"""
**File:** ``aws.py``
**Region:** ``ds_provider_aws_py_lib/linked_service/aws``

AWS Linked Service

This module implements a linked service for AWS.
"""

from dataclasses import dataclass, field
from typing import Generic, TypeVar

import boto3
from botocore.exceptions import ClientError
from ds_common_logger_py_lib import Logger
from ds_resource_plugin_py_lib.common.resource.linked_service import LinkedService, LinkedServiceSettings
from ds_resource_plugin_py_lib.common.resource.linked_service.errors import AuthorizationError, ConnectionError

from ..enums import ResourceType

logger = Logger.get_logger(__name__, package=True)


@dataclass(kw_only=True)
class AWSLinkedServiceSettings(LinkedServiceSettings):
    """
    The object containing the AWS linked service settings.
    """

    account_id: str
    """The AWS account ID."""
    access_key_id: str
    """The AWS access key ID."""
    access_key_secret: str = field(metadata={"mask": True})
    """The AWS access key secret."""
    region: str = "eu-north-1"
    """The AWS region."""


AWSLinkedServiceSettingsType = TypeVar(
    "AWSLinkedServiceSettingsType",
    bound=AWSLinkedServiceSettings,
)


@dataclass(kw_only=True)
class AWSLinkedService(LinkedService[AWSLinkedServiceSettingsType], Generic[AWSLinkedServiceSettingsType]):
    """
    The class is used to connect with AWS services.
    """

    settings: AWSLinkedServiceSettingsType
    _connection: boto3.Session | None = field(default=None, init=False, repr=False, metadata={"serialize": False})

    @property
    def type(self) -> ResourceType:
        """
        Get the type of the linked service.

        Returns:
            ResourceType
        """
        return ResourceType.LINKED_SERVICE

    @property
    def connection(self) -> boto3.Session:
        """
        Get the connection to AWS.

        Returns:
            boto3.Session: The established boto3 session.
        """
        if self._connection is None:
            raise ConnectionError("No AWS session available. Call connect() first.")
        return self._connection

    def connect(self) -> None:
        """
        Create a boto3 session using the provided AWS credentials and verify the account ID if specified.

        Raises:
            AuthorizationError: If the AWS account ID does not match the expected value.
        """
        logger.debug(
            "Connecting to AWS account_id=%s in region=%s",
            self.settings.account_id,
            self.settings.region,
        )
        session = boto3.Session(
            aws_account_id=self.settings.account_id,
            region_name=self.settings.region,
            aws_access_key_id=self.settings.access_key_id,
            aws_secret_access_key=self.settings.access_key_secret,
        )
        sts_client = session.client("sts")
        try:
            identity = sts_client.get_caller_identity()
            actual_account_id = identity.get("Account")
        except ClientError as exc:
            logger.error("Unable to verify AWS account ID: %s", exc)
            raise AuthorizationError(
                message="Unable to verify AWS account ID.",
                details={
                    "type": self.type.value,
                    "expected_account_id": self.settings.account_id,
                },
            ) from exc

        if actual_account_id != self.settings.account_id:
            raise AuthorizationError(
                message=f"Unable to verify AWS account ID. "
                f"{actual_account_id} does not match expected value: {self.settings.account_id}",
                details={
                    "type": self.type.value,
                    "expected_account_id": self.settings.account_id,
                    "actual_account_id": actual_account_id,
                },
            )
        self._connection = session

    def test_connection(self) -> tuple[bool, str]:
        """
        Test the connection to AWS by creating the session.

        Returns:
            tuple[bool, str]: A tuple containing a boolean indicating success and a message.
        """
        try:
            self.connect()
            return True, "Connection successfully tested"
        except ClientError as exc:
            return False, str(exc)

    def close(self) -> None:
        """
        boto3 sessions do not require explicit closing.
        """
        pass
