"""
**File:** ``test_enums.py``
**Region:** ``tests/test_enums``

ResourceType enum tests.

Covers:
- Enum value definitions and string representations.
- Enum membership and comparison operations.
"""

from __future__ import annotations

from ds_provider_aws_py_lib.enums import ResourceType


def test_resource_type_linked_service_value() -> None:
    """
    It exposes the correct linked service type value.
    """
    assert ResourceType.LINKED_SERVICE == "ds.resource.linked-service.aws"
    assert isinstance(ResourceType.LINKED_SERVICE, str)


def test_resource_type_enum_membership() -> None:
    """
    It allows checking enum membership.
    """
    assert ResourceType.LINKED_SERVICE in ResourceType


def test_resource_type_enum_comparison() -> None:
    """
    It supports equality comparison with strings.
    """
    assert ResourceType.LINKED_SERVICE == "ds.resource.linked-service.aws"


def test_s3_type_enum_comparison() -> None:
    """
    It supports equality comparison with strings.
    """
    assert ResourceType.S3_DATASET == "ds.resource.dataset.s3"
