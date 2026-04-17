"""
**File:** ``__init__.py``
**Region:** ``ds_provider_aws_py_lib/dataset``

AWS Dataset

This module implements a dataset for AWS (S3)

Example:
   >>> linked_service = AWSLinkedService(
   ...     id=UUID("00000000-0000-0000-0000-000000000000"),
   ...     name="test-name",
   ...     version="1.0.0",
   ...     settings=AWSLinkedServiceSettings(
   ...         account_id="...",
   ...         access_key_id="...",
   ...         access_key_secret="...",
   ...         region="us-east-1",
   ...     ),
   ... )
   >>> dataset = S3Dataset(
   ...     id=UUID("00000000-0000-0000-0000-000000000001"),
   ...     name="test-s3-dataset",
   ...     version="1.0.0",
   ...     settings=S3DatasetSettings(
   ...         bucket="test-package",
   ...         key="test3/*.csv",
   ...     ),
   ...     linked_service=linked_service,
   ... )
   >>> dataset.read()
   >>> data = dataset.output
"""

from .s3 import S3Dataset, S3DatasetSettings

__all__ = [
    "S3Dataset",
    "S3DatasetSettings",
]
