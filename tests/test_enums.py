"""
**File:** ``test_enums.py``
**Region:** ``tests/test_enums``

ResourceKind enum tests.

Covers:
- Enum value definitions and string representations.
- Enum membership and comparison operations.
"""

from __future__ import annotations

from ds_provider_aws_py_lib.enums import ResourceKind


def test_resource_kind_linked_service_value() -> None:
    """
    It exposes the correct linked service kind value.
    """
    assert ResourceKind.LINKED_SERVICE == "DS.RESOURCE.LINKED_SERVICE.AWS"
    assert isinstance(ResourceKind.LINKED_SERVICE, str)


def test_resource_kind_enum_membership() -> None:
    """
    It allows checking enum membership.
    """
    assert ResourceKind.LINKED_SERVICE in ResourceKind


def test_resource_kind_enum_comparison() -> None:
    """
    It supports equality comparison with strings.
    """
    assert ResourceKind.LINKED_SERVICE == "DS.RESOURCE.LINKED_SERVICE.AWS"
