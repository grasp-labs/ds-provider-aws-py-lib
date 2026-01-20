from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

import boto3
from botocore.exceptions import ClientError
from ds_resource_plugin_py_lib.common.resource.linked_service import LinkedService, LinkedServiceSettings

from ..enums import ResourceKind


@dataclass(kw_only=True)
class AWSLinkedServiceSettings(LinkedServiceSettings):
    """
    The object containing the AWS linked service settings.
    """

    aws_account_id: str = "999125116186"
    access_key_id: str | None = None
    access_key_secret: str | None = None
    region: str = "eu-north-1"


AWSLinkedServiceSettingsType = TypeVar(
    "AWSLinkedServiceSettingsType",
    bound=AWSLinkedServiceSettings,
)


@dataclass(kw_only=True)
class AWSLinkedService(LinkedService[AWSLinkedServiceSettingsType], Generic[AWSLinkedServiceSettingsType]):
    """
    The class is used to connect with AWS S3.
    """

    settings: AWSLinkedServiceSettingsType

    def connect(self) -> boto3.Session:
        session = boto3.Session(
            aws_account_id=self.settings.aws_account_id,
            region_name=self.settings.region,
            aws_access_key_id=self.settings.access_key_id,
            aws_secret_access_key=self.settings.access_key_secret,
        )
        return session

    def test_connection(self) -> tuple[bool, str]:
        try:
            connection = self.connect()
            connection.client("s3").list_buckets()
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
