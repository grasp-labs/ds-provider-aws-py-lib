"""
**File:** ``test_linked_service.py``
**Region:** ``tests/linked_service/unit_test``

Description
-----------
Unit tests for AWS linked service connection and account ID verification.
"""

from __future__ import annotations

from uuid import UUID

from botocore.exceptions import ClientError

from ds_provider_aws_py_lib.linked_service.aws import AWSLinkedService, AWSLinkedServiceSettings

TEST_UUID = UUID("00000000-0000-0000-0000-000000000000")


class DummyClient:
    """
    A dummy AWS client that simulates basic AWS client behavior for testing.
    """

    def __init__(self, **kwargs):
        self.account_id = kwargs.get("aws_account_id")

    def list_buckets(self):
        return {"Buckets": []}

    def get_caller_identity(self):
        return {"Account": self.account_id}


class DummySession:
    """
    A dummy AWS session that simulates basic AWS session behavior for testing.
    """

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def client(self, service: str):
        return DummyClient(**self.kwargs)


def test_connect_uses_settings(monkeypatch):
    """
    Test that AWSLinkedService.connect() uses the settings to create a session.
    """
    settings = AWSLinkedServiceSettings(
        account_id="123",
        access_key_id="AK",
        access_key_secret="SK",
        region="us-west-2",
    )
    captured: dict = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return DummySession(**kwargs)

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = AWSLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=settings)
    sess = ls.connect()

    assert isinstance(sess, DummySession)
    assert captured["aws_account_id"] == "123"
    assert captured["aws_access_key_id"] == "AK"
    assert captured["aws_secret_access_key"] == "SK"
    assert captured["region_name"] == "us-west-2"


def test_test_connection_success(monkeypatch):
    """
    Test that AWSLinkedService.test_connection() returns success (indicating that the client works).
    """
    settings = AWSLinkedServiceSettings(access_key_id=..., access_key_secret=..., account_id="321")

    def fake_session(**kwargs):
        return DummySession(aws_account_id="321")

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = AWSLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=settings)
    ok, msg = ls.test_connection()

    assert ok is True
    assert "successfully" in msg.lower()


def test_test_connection_clienterror(monkeypatch):
    """
    Test that AWSLinkedService.test_connection() returns failure when the client raises ClientError.
    """
    settings = AWSLinkedServiceSettings(access_key_id=..., access_key_secret=..., account_id=...)

    def fake_session(**kwargs):
        class BadSession:
            def client(self, service: str):
                raise ClientError({"Error": {"Message": "denied", "Code": "403"}}, "ListBuckets")

        return BadSession()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = AWSLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=settings)
    ok, msg = ls.test_connection()

    assert ok is False
    assert "denied" in msg


def test_raises_on_account_id_mismatch(monkeypatch):
    """
    Test that AWSLinkedService.connect() raises an error when the account ID does not match.
    """
    settings = AWSLinkedServiceSettings(
        account_id="expected-account-id",
        access_key_id="AK",
        access_key_secret="SK",
    )

    def fake_session(**kwargs):
        return DummySession(account_id="actual-account-id")

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = AWSLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=settings)
    try:
        ls.connect()
    except Exception as exc:
        assert "does not match expected value" in str(exc)


def test_excepts_on_sts_client_error(monkeypatch):
    """
    Test that AWSLinkedService.connect() raises an error when the STS client fails
    """
    settings = AWSLinkedServiceSettings(
        account_id="expected-account-id",
        access_key_id="AK",
        access_key_secret="SK",
    )

    def fake_session(**kwargs):
        class BadSession:
            def client(self, service: str):
                class BadClient:
                    def get_caller_identity(self):
                        raise ClientError({"Error": {"Message": "STS error", "Code": "403"}}, "GetCallerIdentity")

                return BadClient()

        return BadSession()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = AWSLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=settings)
    try:
        ls.connect()
    except Exception as exc:
        assert "Unable to verify AWS account ID" in str(exc)
