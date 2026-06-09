"""
**File:** ``tenant_partition.py``
**Region:** ``ds_provider_aws_py_lib/linked_service``

Per-tenant S3 partition linked services backed by IAM role assumption.

Each tenant has two IAM roles provisioned by ds-data-partition-provision:
- ``ds-{tenant_id}-{building_mode}-reader``  — read-only S3 access
- ``ds-{tenant_id}-{building_mode}-admin``   — read + write S3 access

``connect()`` calls ``sts:AssumeRole`` using the ambient execution credentials
(instance profile / ECS task role / etc.) and stores the resulting boto3 Session.
"""

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

import boto3
from botocore.exceptions import ClientError
from ds_common_logger_py_lib import Logger
from ds_resource_plugin_py_lib.common.resource.linked_service import LinkedService, LinkedServiceSettings
from ds_resource_plugin_py_lib.common.resource.linked_service.errors import AuthenticationError, ConnectionError

from ..enums import ResourceType

logger = Logger.get_logger(__name__, package=True)


@dataclass(kw_only=True)
class TenantPartitionSettings(LinkedServiceSettings):
    """Settings for per-tenant partition linked services."""

    tenant_id: UUID
    """The tenant UUID — used to derive the IAM role name and S3 bucket name."""
    building_mode: str
    """Deployment environment: ``dev``, ``prod``, or ``sandbox``."""
    region: str = "eu-north-1"
    """AWS region (defaults to eu-north-1)."""


TenantPartitionSettingsType = TypeVar("TenantPartitionSettingsType", bound=TenantPartitionSettings)


@dataclass(kw_only=True)
class _TenantPartitionBase(LinkedService[TenantPartitionSettingsType], Generic[TenantPartitionSettingsType]):
    """
    Abstract base for tenant partition linked services.

    Assumes the tenant's IAM role and exposes the resulting boto3 Session.
    Subclasses differ only in which role suffix they target (reader vs. admin).
    """

    settings: TenantPartitionSettingsType
    _connection: boto3.Session | None = field(default=None, init=False, repr=False, metadata={"serialize": False})

    @property
    @abstractmethod
    def type(self) -> StrEnum: ...

    @abstractmethod
    def _role_suffix(self) -> str:
        """Return ``'reader'`` or ``'admin'``."""
        ...

    def _role_arn(self, account_id: str) -> str:
        name = f"ds-{self.settings.tenant_id!s}-{self.settings.building_mode}-{self._role_suffix()}"
        return f"arn:aws:iam::{account_id}:role/{name}"

    def connect(self) -> None:
        """
        Assume the tenant IAM role and store the resulting boto3 Session.

        Uses the ambient execution credentials (instance profile / ECS task role)
        to call ``sts:AssumeRole`` — no static credentials required.

        Raises:
            AuthenticationError: If STS returns AccessDenied for the role assumption.
            ConnectionError: If any other STS ``ClientError`` occurs.
        """
        logger.debug(
            "Connecting to tenant partition tenant_id=%s building_mode=%s role=%s",
            self.settings.tenant_id,
            self.settings.building_mode,
            self._role_suffix(),
        )
        try:
            sts = boto3.client("sts", region_name=self.settings.region)
            account_id = sts.get_caller_identity()["Account"]
            role_arn = self._role_arn(account_id)
            assumed = sts.assume_role(
                RoleArn=role_arn,
                RoleSessionName=f"tenant-partition-{self.settings.tenant_id!s}",
            )
            creds = assumed["Credentials"]
            self._connection = boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                region_name=self.settings.region,
            )
            logger.debug("Assumed role %s for tenant %s", role_arn, self.settings.tenant_id)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("AccessDenied", "AccessDeniedException"):
                raise AuthenticationError(
                    message=f"Cannot assume tenant partition role: {code}",
                    details={
                        "tenant_id": str(self.settings.tenant_id),
                        "building_mode": self.settings.building_mode,
                        "role_suffix": self._role_suffix(),
                        "error": str(exc),
                    },
                ) from exc
            raise ConnectionError(
                message=f"STS call failed: {code}",
                details={"error": str(exc)},
            ) from exc

    @property
    def connection(self) -> boto3.Session:
        """
        Return the assumed-role boto3 Session.

        Raises:
            ConnectionError: If ``connect()`` has not been called.
        """
        if self._connection is None:
            raise ConnectionError("No session available. Call connect() first.")
        return self._connection

    def test_connection(self) -> tuple[bool, str]:
        """
        Test the connection by performing the role assumption.

        Returns:
            ``(True, "Connection successfully tested")`` on success.
            ``(False, "<error description>")`` on any failure.
        """
        try:
            self.connect()
            return True, "Connection successfully tested"
        except Exception as exc:
            return False, str(exc)

    def close(self) -> None:
        """boto3 Sessions do not require explicit closing."""
        pass


@dataclass(kw_only=True)
class TenantPartitionReaderLinkedService(_TenantPartitionBase[TenantPartitionSettings]):
    """Read-only access to a tenant's S3 partition bucket via IAM role assumption."""

    @property
    def type(self) -> ResourceType:
        return ResourceType.TENANT_PARTITION_READER_LINKED_SERVICE

    def _role_suffix(self) -> str:
        return "reader"


@dataclass(kw_only=True)
class TenantPartitionAdminLinkedService(_TenantPartitionBase[TenantPartitionSettings]):
    """Admin (read + write) access to a tenant's S3 partition bucket via IAM role assumption."""

    @property
    def type(self) -> ResourceType:
        return ResourceType.TENANT_PARTITION_ADMIN_LINKED_SERVICE

    def _role_suffix(self) -> str:
        return "admin"
