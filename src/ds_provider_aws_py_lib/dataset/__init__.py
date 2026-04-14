"""
**File:** ``__init__.py``
**Region:** ``ds_provider_aws_py_lib/dataset``

AWS Dataset

This module implements a dataset for AWS (S3)

Example:
    ... # todo
"""

from .s3 import S3Dataset, S3DatasetSettings, S3UpdateStrategy

__all__ = [
    "S3Dataset",
    "S3DatasetSettings",
    "S3UpdateStrategy",
]
