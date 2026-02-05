"""
**File:** ``test_connect.py``
**Region:** ``tests/unit_test``

Description
-----------
Unit tests for AWS linked service connection testing, focusing on exception handling.
"""

from __future__ import annotations

import sys
import types
from uuid import UUID

import ds_provider_aws_py_lib.linked_service.aws as aws_mod
from ds_provider_aws_py_lib.linked_service.aws import AWSLinkedService, AWSLinkedServiceSettings

TEST_UUID = UUID("00000000-0000-0000-0000-000000000000")


def test_connection_client_exception(monkeypatch):
    """Simulate a non-ClientError raised by the S3 client to cover generic-exception handling."""

    def fake_session(**kwargs):
        class BadSession:
            def client(self, service: str):
                class BadClient:
                    def get_caller_identity(self):
                        raise Exception("boom")

                return BadClient()

        return BadSession()

    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.Session = fake_session
    fake_boto3.client = lambda service: fake_session().client(service)

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setattr(aws_mod, "boto3", fake_boto3)
    monkeypatch.setattr(aws_mod, "Session", fake_session, raising=False)

    ls = AWSLinkedService(
        id=TEST_UUID,
        name="test-name",
        version="1.0.0",
        settings=AWSLinkedServiceSettings(access_key_id=..., access_key_secret=..., account_id=...),
    )

    try:
        ok, msg = ls.test_connection()
    except Exception as exc:
        assert "boom" in str(exc).lower()
    else:
        assert ok is False
        assert "boom" in msg.lower()


def test_connection_session_exception(monkeypatch):
    """Simulate session construction failing to cover that error path."""

    def bad_session(**kwargs):
        raise Exception("session fail")

    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.Session = bad_session

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setattr(aws_mod, "boto3", fake_boto3)
    monkeypatch.setattr(aws_mod, "Session", bad_session, raising=False)

    ls = AWSLinkedService(
        id=TEST_UUID,
        name="test-name",
        version="1.0.0",
        settings=AWSLinkedServiceSettings(access_key_id=..., access_key_secret=..., account_id=...),
    )

    try:
        ok, msg = ls.test_connection()
    except Exception as exc:
        assert "session fail" in str(exc).lower()
    else:
        assert ok is False
        assert "session fail" in msg.lower()
