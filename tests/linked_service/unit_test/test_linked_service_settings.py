"""
**File:** ``test_linked_service_settings.py``
**Region:** ``tests/linked_service/unit_test``

Description
-----------
AWSLinkedService settings and initialization tests.

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
    AWSLinkedService,
    AWSLinkedServiceSettings,
)

TEST_UUID = UUID("00000000-0000-0000-0000-000000000000")


def test_create_default_linked_service() -> None:
    """
    It creates an AwsLinkedService with default settings.
    """
    props = AWSLinkedServiceSettings(access_key_id="ABC", access_key_secret="DEF", account_id="123")
    linked_service = AWSLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=props)
    assert isinstance(linked_service, AWSLinkedService)
    assert linked_service.settings.account_id == "123"
    assert linked_service.settings.access_key_id == "ABC"
    assert linked_service.settings.access_key_secret == "DEF"
    assert linked_service.settings.region == "eu-north-1"


def test_linked_service_type_is_linked_service() -> None:
    """
    It exposes linked service type.
    """
    props = AWSLinkedServiceSettings(region="us-west-2", access_key_id=..., access_key_secret=..., account_id=...)
    linked_service = AWSLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=props)
    assert linked_service.type == ResourceType.LINKED_SERVICE
    assert linked_service.settings.region == "us-west-2"


def test_session_and_client_none_before_connect() -> None:
    """
    It returns None for session/client properties before connect() is called.
    Uses getattr to avoid failing if an attribute is not present.
    """
    props = AWSLinkedServiceSettings(access_key_id=..., access_key_secret=..., account_id=...)
    linked_service = AWSLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=props)
    assert getattr(linked_service, "session", None) is None
    assert getattr(linked_service, "s3_client", None) is None
    assert getattr(linked_service, "client", None) is None


def test_settings_initialization_defaults() -> None:
    """
    It initializes settings with default (None) values.
    """
    props = AWSLinkedServiceSettings(access_key_id=..., access_key_secret=..., account_id="321")
    assert props.account_id == "321"
    assert props.region == "eu-north-1"


def test_settings_custom_values() -> None:
    """
    It accepts custom AWS credential and region values.
    """
    props = AWSLinkedServiceSettings(
        account_id="123",
        access_key_id="AK",
        access_key_secret="SK",
        region="us-west-2",
    )
    assert props.account_id == "123"
    assert props.access_key_id == "AK"
    assert props.access_key_secret == "SK"
    assert props.region == "us-west-2"


def test_close_does_not_raise():
    ls = AWSLinkedService(
        id=TEST_UUID,
        name="test-name",
        version="1.0.0",
        settings=AWSLinkedServiceSettings(access_key_id=..., access_key_secret=..., account_id=...),
    )
    with nullcontext():
        ls.close()
