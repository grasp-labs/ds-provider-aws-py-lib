from __future__ import annotations

from botocore.exceptions import ClientError

from ds_provider_aws_py_lib.linked_service.aws import AwsLinkedService, AWSLinkedServiceSettings


class DummyClient:
    def list_buckets(self):
        return {"Buckets": []}


class DummySession:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def client(self, service: str):
        assert service == "s3"
        return DummyClient()


def test_connect_uses_settings(monkeypatch):
    settings = AWSLinkedServiceSettings(
        aws_account_id="123",
        access_key_id="AK",
        access_key_secret="SK",
        region="us-west-2",
    )
    captured: dict = {}

    def fake_session(**kwargs):
        captured.update(kwargs)
        return DummySession(**kwargs)

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = AwsLinkedService(settings=settings)
    sess = ls.connect()

    assert isinstance(sess, DummySession)
    assert captured["aws_account_id"] == "123"
    assert captured["aws_access_key_id"] == "AK"
    assert captured["aws_secret_access_key"] == "SK"
    assert captured["region_name"] == "us-west-2"


def test_test_connection_success(monkeypatch):
    settings = AWSLinkedServiceSettings()

    def fake_session(**kwargs):
        return DummySession()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = AwsLinkedService(settings=settings)
    ok, msg = ls.test_connection()

    assert ok is True
    assert "successfully" in msg.lower()


def test_test_connection_clienterror(monkeypatch):
    settings = AWSLinkedServiceSettings()

    def fake_session(**kwargs):
        class BadSession:
            def client(self, service: str):
                raise ClientError({"Error": {"Message": "denied", "Code": "403"}}, "ListBuckets")

        return BadSession()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = AwsLinkedService(settings=settings)
    ok, msg = ls.test_connection()

    assert ok is False
    assert "denied" in msg
