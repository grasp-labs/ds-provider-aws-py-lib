import os

import pytest

from ds_provider_aws_py_lib.linked_service.aws import AWSLinkedService, AWSLinkedServiceSettings

pytestmark = pytest.mark.integration


def test_connect_creates_session_and_clients():
    access_key_id = os.environ.get("AWS-ACCESS-KEY-ID")
    access_key_secret = os.environ.get("AWS-SECRET-ACCESS-KEY")
    settings = AWSLinkedServiceSettings(access_key_id=access_key_id, access_key_secret=access_key_secret)
    aws_linked_service = AWSLinkedService(settings=settings)
    result = aws_linked_service.test_connection()
    assert result == (True, "Connection successfully tested")
