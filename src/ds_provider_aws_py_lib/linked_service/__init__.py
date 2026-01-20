"""
**File:** ``__init__.py``
**Region:** ``ds_provider_aws_py_lib/linked_service``

AWS Linked Service

This module implements a linked service for AWS (for example, S3) and provides a boto3 session.

Example:
    >>> aws_linked_service = AwsLinkedService(settings=AWSLinkedServiceSettings(
    ...    account_id="your_account_id",
    ...    access_key_id="your_access",
    ...    access_key_secret="your_secret",
    ... ))
    >>> session = aws_linked_service.connect()
"""

from .aws import AWSLinkedService, AWSLinkedServiceSettings

__all__ = [
    "AWSLinkedService",
    "AWSLinkedServiceSettings",
]
