"""
**File:** ``__init__.py``
**Region:** ``ds_provider_aws_py_lib/linked_service``

AWS Linked Service

This module implements linked services for AWS (for example, S3) and provides a boto3 session.

Two authentication strategies are available:

- :class:`AWSLinkedService` — authenticates with an IAM user access key and secret.
- :class:`AWSIAMRoleLinkedService` — **internal use only**; assumes an IAM role using
  the service's ambient credentials (instance profile, ECS task role, etc.).

Example:
    >>> linked_service = AWSLinkedService(
    ...     id=UUID("00000000-0000-0000-0000-000000000000"),
    ...     name="test-name",
    ...     version="1.0.0",
    ...     settings=AWSLinkedServiceSettings(
    ...         account_id="your_account_id",
    ...         access_key_id="your_access",
    ...         access_key_secret="your_secret",
    ...         region="us-west-2",
    ...     ),
    ... )
    >>> linked_service.test_connection()
"""

from .aws import AWSIAMRoleLinkedService, AWSIAMRoleLinkedServiceSettings, AWSLinkedService, AWSLinkedServiceSettings
from .tenant_partition import (
    TenantPartitionAdminLinkedService,
    TenantPartitionReaderLinkedService,
    TenantPartitionSettings,
)

__all__ = [
    "AWSIAMRoleLinkedService",
    "AWSIAMRoleLinkedServiceSettings",
    "AWSLinkedService",
    "AWSLinkedServiceSettings",
    "TenantPartitionReaderLinkedService",
    "TenantPartitionAdminLinkedService",
    "TenantPartitionSettings",
]
