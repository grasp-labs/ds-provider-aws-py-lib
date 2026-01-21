"""
**File:** ``enums.py``
**Region:** ``ds_provider_aws_py_lib/enums``

Constants for AWS provider.

Example:
    >>> ResourceType.LINKED_SERVICE
    'DS.RESOURCE.LINKED_SERVICE.AWS'
"""

from enum import StrEnum


class ResourceType(StrEnum):
    """
    Constants for AWS provider.
    """

    LINKED_SERVICE = "DS.RESOURCE.LINKED_SERVICE.AWS"
