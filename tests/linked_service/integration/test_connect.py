"""
**File:** ``test_connection.py``
**Region:** ``tests/linked_service/integration``

Description
-----------
Integration tests that verify AWS linked service can connect and create clients. Environment variables needs to
be set for AWS credentials:
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_ACCOUNT_ID
"""

import os
from uuid import UUID

import pytest

from ds_provider_aws_py_lib.linked_service.aws import AWSLinkedService, AWSLinkedServiceSettings

TEST_UUID = UUID("00000000-0000-0000-0000-000000000000")

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    not os.environ.get("AWS_ACCOUNT_ID") and not os.environ.get("AWS-ACCOUNT-ID"),
    reason="AWS_ACCOUNT_ID environment variable not set",
)
def test_connect_creates_session_and_clients():
    # given
    access_key_id = os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS-ACCESS-KEY-ID")
    access_key_secret = os.environ.get("AWS_SECRET_ACCESS_KEY") or os.environ.get("AWS-SECRET-ACCESS-KEY")
    account_id = os.environ.get("AWS_ACCOUNT_ID") or os.environ.get("AWS-ACCOUNT-ID")
    assert access_key_id is not None
    assert access_key_secret is not None
    assert account_id is not None
    settings = AWSLinkedServiceSettings(access_key_id=access_key_id, access_key_secret=access_key_secret, account_id=account_id)
    aws_linked_service = AWSLinkedService(id=TEST_UUID, name="test-name", version="1.0.0", settings=settings)
    # when
    aws_linked_service.connect()
    result = aws_linked_service.connection.client("sts").get_caller_identity()
    # then
    assert "Account" in result
    assert "UserId" in result
    assert "Arn" in result
