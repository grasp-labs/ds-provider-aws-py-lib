import pytest

from ds_provider_aws_py_lib.linked_service.aws import AwsLinkedService, AWSLinkedServiceSettings

pytestmark = pytest.mark.integration


def test_connect_creates_session_and_clients():
    settings = AWSLinkedServiceSettings()
    aws_linked_service = AwsLinkedService(settings=settings)
    result = aws_linked_service.test_connection()
    assert result == (True, "Connection successfully tested")


test_connect_creates_session_and_clients()
