"""
**File:** ``aws.py``
**Region:** ``ds_provider_aws_py_lib/linked_service/aws``

AWS Linked Service

This module implements a linked service for AWS.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar

import boto3
from botocore.exceptions import ClientError
from ds_resource_plugin_py_lib.common.resource.linked_service import LinkedService, LinkedServiceSettings
from ds_resource_plugin_py_lib.common.resource.linked_service.errors import AuthorizationError

from ..enums import ResourceKind


@dataclass(kw_only=True)
class AWSLinkedServiceSettings(LinkedServiceSettings):
    """
    The object containing the AWS linked service settings.
    """

    account_id: str
    access_key_id: str
    access_key_secret: str
    region: str = "eu-north-1"


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
    session: boto3.Session | None = field(default=None, init=False, repr=False)

    def connect(self) -> boto3.Session:
        """
        Create a boto3 session using the provided AWS credentials and verify the account ID if specified.
        Returns:
            boto3.Session: The established boto3 session.
        Raises:
            AuthorizationError: If the AWS account ID does not match the expected value.
        """
        self.session = boto3.Session(
            aws_account_id=self.settings.account_id,
            region_name=self.settings.region,
            aws_access_key_id=self.settings.access_key_id,
            aws_secret_access_key=self.settings.access_key_secret,
        )
        sts_client = self.session.client("sts")
        try:
            identity = sts_client.get_caller_identity()
            actual_account_id = identity.get("Account")
        except ClientError as exc:
            raise AuthorizationError(
                message="Unable to verify AWS account ID.",
                details={"expected_account_id": self.settings.account_id},
            ) from exc

        if actual_account_id != self.settings.account_id:
            raise AuthorizationError(
                message="AWS account ID does not match expected value.",
                details={
                    "expected_account_id": self.settings.account_id,
                    "actual_account_id": actual_account_id,
                },
            )

        return self.session

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

    @property
    def kind(self) -> StrEnum:
        """
        Get the kind of the linked service.
        Returns:
            ResourceKind
        """
        return ResourceKind.LINKED_SERVICE
