"""
**File:** ``test_connection.py``
**Region:** ``tests/linked_service/integration``

Description
-----------
Integration tests that verify AWS linked service can connect and create clients. Environment variables needs to
be set for AWS credentials:
- AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
"""

import os

import pytest

from ds_provider_aws_py_lib.linked_service.aws import AWSLinkedService, AWSLinkedServiceSettings

pytestmark = pytest.mark.integration


def test_connect_creates_session_and_clients():
    # given
    access_key_id = os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS-ACCESS-KEY-ID")
    access_key_secret = os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("AWS-SECRET-ACCESS-KEY")
    account_id = os.environ.get("AWS_ACCOUNT_ID")
    settings = AWSLinkedServiceSettings(access_key_id=access_key_id, access_key_secret=access_key_secret, account_id=account_id)
    aws_linked_service = AWSLinkedService(settings=settings)
    # when
    connection = aws_linked_service.connect()
    result = connection.client("sts").get_caller_identity()
    # then
    assert "Account" in result
    assert "UserId" in result
    assert "Arn" in result
