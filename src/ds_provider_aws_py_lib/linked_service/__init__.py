"""
**File:** ``__init__.py``
**Region:** ``ds_provider_aws_py_lib/linked_service``

AWS Linked Service

This module implements a linked service for AWS (for example, S3) and provides a boto3 session.

Example:
    >>> inked_service = AWSLinkedService(
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
    >>> linked_service.connect()
    >>> linked_service.test_connection()
"""

from .aws import AWSLinkedService, AWSLinkedServiceSettings

__all__ = [
    "AWSLinkedService",
    "AWSLinkedServiceSettings",
]
