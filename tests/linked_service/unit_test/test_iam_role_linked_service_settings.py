"""
**File:** ``test_iam_role_linked_service_settings.py``
**Region:** ``tests/linked_service/unit_test``

Description
-----------
AWSIAMRoleLinkedService settings and initialization tests.

Covers:
- Linked service type.
- Session / client access before connection.
- Settings initialization and default values.
"""

from __future__ import annotations

from contextlib import nullcontext
from uuid import UUID

from ds_provider_aws_py_lib.enums import ResourceType
from ds_provider_aws_py_lib.linked_service.aws import (
    AWSIAMRoleLinkedService,
    AWSIAMRoleLinkedServiceSettings,
)

TEST_UUID = UUID("00000000-0000-0000-0000-000000000000")


def test_create_default_settings() -> None:
    """
    It creates settings with the default region.
    """
    props = AWSIAMRoleLinkedServiceSettings(
        account_id="123456789012",
        role_arn="arn:aws:iam::123456789012:role/test-role",
    )
    assert props.account_id == "123456789012"
    assert props.role_arn == "arn:aws:iam::123456789012:role/test-role"
    assert props.region == "eu-north-1"


def test_settings_custom_values() -> None:
    """
    It accepts custom account ID, role ARN and region values.
    """
    props = AWSIAMRoleLinkedServiceSettings(
        account_id="123456789012",
        role_arn="arn:aws:iam::123456789012:role/test-role",
        region="us-west-2",
    )
    assert props.account_id == "123456789012"
    assert props.role_arn == "arn:aws:iam::123456789012:role/test-role"
    assert props.region == "us-west-2"


def test_linked_service_type_is_linked_service() -> None:
    """
    It exposes linked service type.
    """
    props = AWSIAMRoleLinkedServiceSettings(
        account_id="123456789012",
        role_arn="arn:aws:iam::123456789012:role/test-role",
    )
    ls = AWSIAMRoleLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=props)
    assert ls.type == ResourceType.LINKED_SERVICE


def test_connection_property_raises_before_connect() -> None:
    """
    It raises ConnectionError when accessing connection before connect() is called.
    """
    from ds_resource_plugin_py_lib.common.resource.linked_service.errors import ConnectionError as LSConnectionError

    props = AWSIAMRoleLinkedServiceSettings(
        account_id="123456789012",
        role_arn="arn:aws:iam::123456789012:role/test-role",
    )
    ls = AWSIAMRoleLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=props)
    try:
        _ = ls.connection
        assert False, "Expected ConnectionError"
    except LSConnectionError:
        pass


def test_close_does_not_raise() -> None:
    """
    It does not raise when close() is called.
    """
    props = AWSIAMRoleLinkedServiceSettings(
        account_id="123456789012",
        role_arn="arn:aws:iam::123456789012:role/test-role",
    )
    ls = AWSIAMRoleLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=props)
    with nullcontext():
        ls.close()
