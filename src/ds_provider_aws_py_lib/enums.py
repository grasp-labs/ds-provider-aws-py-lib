"""
**File:** ``enums.py``
**Region:** ``ds_provider_aws_py_lib/enums``

Constants for PostgreSQL provider.

Example:
    >>> ResourceKind.LINKED_SERVICE
    'DS.RESOURCE.LINKED_SERVICE.AWS'
    >>> ResourceKind.DATASET
    'DS.RESOURCE.DATASET.AWS'
"""

from enum import StrEnum


class ResourceKind(StrEnum):
    """
    Constants for AWS provider.
    """

    LINKED_SERVICE = "DS.RESOURCE.LINKED_SERVICE.AWS"
    DATASET = "DS.RESOURCE.DATASET.AWS"
