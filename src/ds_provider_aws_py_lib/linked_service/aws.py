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
class AWSIAMRoleLinkedServiceSettings(LinkedServiceSettings):
    """
    The object containing the AWS IAM role linked service settings.

    **Internal use only.** Uses the service's ambient credentials (instance profile,
    task role, etc.) to assume the given IAM role via sts:AssumeRole. No access keys
    are required.
    """

    account_id: str
    """The AWS account ID that owns the role."""
    role_arn: str
    """The ARN of the IAM role to assume."""
    region: str = "eu-north-1"
    """The AWS region."""


AWSIAMRoleLinkedServiceSettingsType = TypeVar(
    "AWSIAMRoleLinkedServiceSettingsType",
    bound=AWSIAMRoleLinkedServiceSettings,
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


@dataclass(kw_only=True)
class AWSIAMRoleLinkedService(
    LinkedService[AWSIAMRoleLinkedServiceSettingsType],
    Generic[AWSIAMRoleLinkedServiceSettingsType],
):
    """
    AWS linked service that assumes an IAM role using the service's ambient credentials.

    **Internal use only.** No access keys are needed. The service must have an AWS
    identity (e.g. EC2 instance profile or ECS task role) with permission to call
    sts:AssumeRole on the target role.
    """

    settings: AWSIAMRoleLinkedServiceSettingsType
    _connection: boto3.Session | None = field(default=None, init=False, repr=False, metadata={"serialize": False})

    @property
    def type(self) -> ResourceType:
        return ResourceType.LINKED_SERVICE

    @property
    def connection(self) -> boto3.Session:
        if self._connection is None:
            raise ConnectionError("No AWS session available. Call connect() first.")
        return self._connection

    def connect(self) -> None:
        """
        Assume the configured IAM role and verify the resulting account ID.

        Raises:
            AuthorizationError: If the role cannot be assumed or the account ID does not match.
        """
        logger.debug(
            "Assuming IAM role=%s in account_id=%s region=%s",
            self.settings.role_arn,
            self.settings.account_id,
            self.settings.region,
        )
        sts_client = boto3.Session(region_name=self.settings.region).client("sts")
        try:
            assumed = sts_client.assume_role(
                RoleArn=self.settings.role_arn,
                RoleSessionName="ds-provider-aws-session",
            )
        except ClientError as exc:
            logger.error("Unable to assume IAM role: %s", exc)
            raise AuthorizationError(
                message="Unable to assume IAM role.",
                details={
                    "type": self.type.value,
                    "role_arn": self.settings.role_arn,
                },
            ) from exc

        creds = assumed["Credentials"]
        role_session = boto3.Session(
            region_name=self.settings.region,
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
        )
        try:
            identity = role_session.client("sts").get_caller_identity()
            actual_account_id = identity.get("Account")
        except ClientError as exc:
            logger.error("Unable to verify AWS account ID after role assumption: %s", exc)
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
        self._connection = role_session

    def test_connection(self) -> tuple[bool, str]:
        """
        Test the connection by assuming the role.

        Returns:
            tuple[bool, str]: A tuple containing a boolean indicating success and a message.
        """
        try:
            self.connect()
            return True, "Connection successfully tested"
        except (ClientError, AuthorizationError) as exc:
            return False, str(exc)

    def close(self) -> None:
        """
        boto3 sessions do not require explicit closing.
        """
        pass
