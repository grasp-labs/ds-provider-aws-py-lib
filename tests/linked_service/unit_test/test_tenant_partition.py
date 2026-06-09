"""
**File:** ``test_tenant_partition.py``
**Region:** ``tests/linked_service/unit_test``

Description
-----------
Unit tests for TenantPartitionReaderLinkedService and TenantPartitionAdminLinkedService.
"""

from __future__ import annotations

from uuid import UUID

import pytest
from botocore.exceptions import ClientError

from ds_provider_aws_py_lib.enums import ResourceType
from ds_provider_aws_py_lib.linked_service.tenant_partition import (
    TenantPartitionAdminLinkedService,
    TenantPartitionReaderLinkedService,
    TenantPartitionSettings,
)

_TEST_UUID = UUID("00000000-0000-0000-0000-000000000000")
_ACCOUNT_ID = "123456789012"
_MODE = "dev"
_REGION = "eu-north-1"
_READER_ROLE_ARN = f"arn:aws:iam::{_ACCOUNT_ID}:role/ds-{_TEST_UUID}-{_MODE}-reader"
_ADMIN_ROLE_ARN = f"arn:aws:iam::{_ACCOUNT_ID}:role/ds-{_TEST_UUID}-{_MODE}-admin"
_ASSUMED_CREDS = {
    "Credentials": {
        "AccessKeyId": "ASIA...",
        "SecretAccessKey": "secret",
        "SessionToken": "token",
    }
}


def _make_reader() -> TenantPartitionReaderLinkedService:
    return TenantPartitionReaderLinkedService(
        id=UUID("11111111-1111-1111-1111-111111111111"),
        name="test-reader",
        version="1.0.0",
        settings=TenantPartitionSettings(
            tenant_id=_TEST_UUID,
            building_mode=_MODE,
            region=_REGION,
        ),
    )


def _make_admin() -> TenantPartitionAdminLinkedService:
    return TenantPartitionAdminLinkedService(
        id=UUID("22222222-2222-2222-2222-222222222222"),
        name="test-admin",
        version="1.0.0",
        settings=TenantPartitionSettings(
            tenant_id=_TEST_UUID,
            building_mode=_MODE,
            region=_REGION,
        ),
    )


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "simulated"}}, "op")


# ── type property ─────────────────────────────────────────────────────────────


def test_reader_type():
    assert _make_reader().type == ResourceType.TENANT_PARTITION_READER_LINKED_SERVICE


def test_admin_type():
    assert _make_admin().type == ResourceType.TENANT_PARTITION_ADMIN_LINKED_SERVICE


# ── settings serialization round-trip ────────────────────────────────────────


def test_settings_round_trip():
    original = TenantPartitionSettings(
        tenant_id=_TEST_UUID,
        building_mode="prod",
        region="us-east-1",
    )
    restored = TenantPartitionSettings.deserialize(original.serialize())
    assert restored.tenant_id == original.tenant_id
    assert restored.building_mode == original.building_mode
    assert restored.region == original.region


def test_settings_default_region():
    s = TenantPartitionSettings(tenant_id=_TEST_UUID, building_mode="dev")
    assert s.region == "eu-north-1"


# ── connection raises before connect() ───────────────────────────────────────


def test_reader_connection_raises_before_connect():
    from ds_resource_plugin_py_lib.common.resource.linked_service.errors import ConnectionError

    with pytest.raises(ConnectionError):
        _ = _make_reader().connection


def test_admin_connection_raises_before_connect():
    from ds_resource_plugin_py_lib.common.resource.linked_service.errors import ConnectionError

    with pytest.raises(ConnectionError):
        _ = _make_admin().connection


# ── connect() — reader assumes reader role ────────────────────────────────────


def test_reader_connect_assumes_reader_role(monkeypatch):
    captured: dict = {}

    class FakeSts:
        def get_caller_identity(self):
            return {"Account": _ACCOUNT_ID}

        def assume_role(self, **kwargs):
            captured.update(kwargs)
            return _ASSUMED_CREDS

    class FakeSession:
        pass

    session_kwargs: dict = {}

    def fake_client(service, **kwargs):
        return FakeSts()

    def fake_session(**kwargs):
        session_kwargs.update(kwargs)
        return FakeSession()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.client", fake_client)
    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.Session", fake_session)

    svc = _make_reader()
    svc.connect()

    assert captured["RoleArn"] == _READER_ROLE_ARN
    assert captured["RoleSessionName"] == f"tenant-partition-{_TEST_UUID!s}"
    assert isinstance(svc.connection, FakeSession)
    assert session_kwargs["aws_access_key_id"] == "ASIA..."
    assert session_kwargs["aws_session_token"] == "token"


# ── connect() — admin assumes admin role ─────────────────────────────────────


def test_admin_connect_assumes_admin_role(monkeypatch):
    captured: dict = {}

    class FakeSts:
        def get_caller_identity(self):
            return {"Account": _ACCOUNT_ID}

        def assume_role(self, **kwargs):
            captured.update(kwargs)
            return _ASSUMED_CREDS

    def fake_client(service, **kwargs):
        return FakeSts()

    def fake_session(**kwargs):
        return object()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.client", fake_client)
    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.Session", fake_session)

    svc = _make_admin()
    svc.connect()

    assert captured["RoleArn"] == _ADMIN_ROLE_ARN


# ── connect() error paths ─────────────────────────────────────────────────────


def test_connect_access_denied_raises_authentication_error(monkeypatch):
    from ds_resource_plugin_py_lib.common.resource.linked_service.errors import AuthenticationError

    class FakeSts:
        def get_caller_identity(self):
            return {"Account": _ACCOUNT_ID}

        def assume_role(self, **kwargs):
            raise _client_error("AccessDenied")

    monkeypatch.setattr(
        "ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.client",
        lambda *a, **kw: FakeSts(),
    )

    with pytest.raises(AuthenticationError, match="Cannot assume tenant partition role"):
        _make_reader().connect()


def test_connect_other_error_raises_connection_error(monkeypatch):
    from ds_resource_plugin_py_lib.common.resource.linked_service.errors import ConnectionError

    class FakeSts:
        def get_caller_identity(self):
            return {"Account": _ACCOUNT_ID}

        def assume_role(self, **kwargs):
            raise _client_error("ServiceUnavailable")

    monkeypatch.setattr(
        "ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.client",
        lambda *a, **kw: FakeSts(),
    )

    with pytest.raises(ConnectionError, match="STS call failed"):
        _make_reader().connect()


# ── test_connection() ─────────────────────────────────────────────────────────


def test_test_connection_success(monkeypatch):
    class FakeSts:
        def get_caller_identity(self):
            return {"Account": _ACCOUNT_ID}

        def assume_role(self, **kwargs):
            return _ASSUMED_CREDS

    monkeypatch.setattr(
        "ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.client",
        lambda *a, **kw: FakeSts(),
    )
    monkeypatch.setattr(
        "ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.Session",
        lambda **kw: object(),
    )

    ok, msg = _make_reader().test_connection()

    assert ok is True
    assert "successfully" in msg.lower()


def test_test_connection_failure_returns_false(monkeypatch):
    class FakeSts:
        def get_caller_identity(self):
            return {"Account": _ACCOUNT_ID}

        def assume_role(self, **kwargs):
            raise _client_error("AccessDenied")

    monkeypatch.setattr(
        "ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.client",
        lambda *a, **kw: FakeSts(),
    )

    ok, msg = _make_reader().test_connection()

    assert ok is False
    assert msg != ""


# ── close() ───────────────────────────────────────────────────────────────────


def test_close_is_idempotent():
    svc = _make_reader()
    svc.close()
    svc.close()


# ── context manager ───────────────────────────────────────────────────────────


def test_context_manager(monkeypatch):
    class FakeSts:
        def get_caller_identity(self):
            return {"Account": _ACCOUNT_ID}

        def assume_role(self, **kwargs):
            return _ASSUMED_CREDS

    monkeypatch.setattr(
        "ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.client",
        lambda *a, **kw: FakeSts(),
    )
    monkeypatch.setattr(
        "ds_provider_aws_py_lib.linked_service.tenant_partition.boto3.Session",
        lambda **kw: object(),
    )

    with _make_reader() as svc:
        svc.connect()
        assert svc._connection is not None
