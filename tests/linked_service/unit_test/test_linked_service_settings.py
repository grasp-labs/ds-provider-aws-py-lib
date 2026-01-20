"""
AWSLinkedService settings and initialization tests.

Covers:
- Linked service kind.
- Session / client access before connection.
- Settings initialization and default values.
"""

from __future__ import annotations

from contextlib import nullcontext

from ds_provider_aws_py_lib.enums import ResourceKind
from ds_provider_aws_py_lib.linked_service.aws import (
    AWSLinkedService,
    AWSLinkedServiceSettings,
)


def test_create_default_linked_service() -> None:
    """
    It creates an AwsLinkedService with default settings.
    """
    props = AWSLinkedServiceSettings()
    linked_service = AWSLinkedService(settings=props)
    assert isinstance(linked_service, AWSLinkedService)
    assert linked_service.settings.aws_account_id == "999125116186"
    assert linked_service.settings.access_key_id is None
    assert linked_service.settings.access_key_secret is None
    assert linked_service.settings.region == "eu-north-1"


def test_linked_service_kind_is_linked_service() -> None:
    """
    It exposes linked service kind.
    """
    props = AWSLinkedServiceSettings(region="us-west-2")
    linked_service = AWSLinkedService(settings=props)
    assert linked_service.kind == ResourceKind.LINKED_SERVICE
    assert linked_service.settings.region == "us-west-2"


def test_session_and_client_none_before_connect() -> None:
    """
    It returns None for session/client properties before connect() is called.
    Uses getattr to avoid failing if an attribute is not present.
    """
    props = AWSLinkedServiceSettings()
    linked_service = AWSLinkedService(settings=props)
    assert getattr(linked_service, "session", None) is None
    assert getattr(linked_service, "s3_client", None) is None
    assert getattr(linked_service, "client", None) is None


def test_settings_initialization_defaults() -> None:
    """
    It initializes settings with default (None) values.
    """
    props = AWSLinkedServiceSettings()
    assert props.aws_account_id == "999125116186"
    assert props.access_key_id is None
    assert props.access_key_secret is None
    assert props.region == "eu-north-1"


def test_settings_custom_values() -> None:
    """
    It accepts custom AWS credential and region values.
    """
    props = AWSLinkedServiceSettings(
        aws_account_id="123",
        access_key_id="AK",
        access_key_secret="SK",
        region="us-west-2",
    )
    assert props.aws_account_id == "123"
    assert props.access_key_id == "AK"
    assert props.access_key_secret == "SK"
    assert props.region == "us-west-2"


def test_close_does_not_raise():
    ls = AWSLinkedService(settings=AWSLinkedServiceSettings())
    with nullcontext():
        ls.close()
