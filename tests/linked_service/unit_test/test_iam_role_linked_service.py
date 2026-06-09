"""
**File:** ``test_iam_role_linked_service.py``
**Region:** ``tests/linked_service/unit_test``

Description
-----------
Unit tests for AWSIAMRoleLinkedService connection and account ID verification.
"""

from __future__ import annotations

from uuid import UUID

from botocore.exceptions import ClientError

from ds_provider_aws_py_lib.linked_service.aws import AWSIAMRoleLinkedService, AWSIAMRoleLinkedServiceSettings

TEST_UUID = UUID("00000000-0000-0000-0000-000000000000")
ROLE_ARN = "arn:aws:iam::123456789012:role/test-role"
ACCOUNT_ID = "123456789012"

FAKE_CREDENTIALS = {
    "AccessKeyId": "TEMP_KEY",
    "SecretAccessKey": "TEMP_SECRET",
    "SessionToken": "TEMP_TOKEN",
}


def _make_fake_session(account_id: str = ACCOUNT_ID, credentials: dict = FAKE_CREDENTIALS):
    """
    Returns a fake boto3.Session factory that handles both the ambient call (assume_role)
    and the role session call (get_caller_identity).
    """

    def fake_session(**kwargs):
        if kwargs.get("aws_access_key_id"):
            # Role session built from temporary credentials.
            class RoleSession:
                def client(self, service: str):
                    class StsClient:
                        def get_caller_identity(self):
                            return {"Account": account_id}

                    return StsClient()

            return RoleSession()
        else:
            # Ambient session used to call assume_role.
            class AmbientSession:
                def client(self, service: str):
                    class StsClient:
                        def assume_role(self, **kw):
                            return {"Credentials": credentials}

                    return StsClient()

            return AmbientSession()

    return fake_session


def _make_linked_service(account_id: str = ACCOUNT_ID, role_arn: str = ROLE_ARN):
    return AWSIAMRoleLinkedService(
        id=TEST_UUID,
        name="test-name",
        version="1.0.0",
        settings=AWSIAMRoleLinkedServiceSettings(
            account_id=account_id,
            role_arn=role_arn,
            region="eu-north-1",
        ),
    )


def test_connect_assumes_role(monkeypatch):
    """
    Test that connect() calls sts:AssumeRole with the configured role ARN and session name.
    """
    captured_assume: dict = {}

    def fake_session(**kwargs):
        if kwargs.get("aws_access_key_id"):

            class RoleSession:
                def client(self, service: str):
                    class StsClient:
                        def get_caller_identity(self):
                            return {"Account": ACCOUNT_ID}

                    return StsClient()

            return RoleSession()
        else:

            class AmbientSession:
                def client(self, service: str):
                    class StsClient:
                        def assume_role(self, **kw):
                            captured_assume.update(kw)
                            return {"Credentials": FAKE_CREDENTIALS}

                    return StsClient()

            return AmbientSession()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = _make_linked_service()
    ls.connect()

    assert captured_assume["RoleArn"] == ROLE_ARN
    assert captured_assume["RoleSessionName"] == "ds-provider-aws-session"


def test_connect_builds_session_with_temp_credentials(monkeypatch):
    """
    Test that connect() builds the role session using the temporary credentials from AssumeRole.
    """
    captured_role_session: dict = {}

    call_count = [0]

    def fake_session(**kwargs):
        call_count[0] += 1
        if call_count[0] == 1:

            class AmbientSession:
                def client(self, service: str):
                    class StsClient:
                        def assume_role(self, **kw):
                            return {"Credentials": FAKE_CREDENTIALS}

                    return StsClient()

            return AmbientSession()
        else:
            captured_role_session.update(kwargs)

            class RoleSession:
                def client(self, service: str):
                    class StsClient:
                        def get_caller_identity(self):
                            return {"Account": ACCOUNT_ID}

                    return StsClient()

            return RoleSession()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = _make_linked_service()
    ls.connect()

    assert captured_role_session["aws_access_key_id"] == FAKE_CREDENTIALS["AccessKeyId"]
    assert captured_role_session["aws_secret_access_key"] == FAKE_CREDENTIALS["SecretAccessKey"]
    assert captured_role_session["aws_session_token"] == FAKE_CREDENTIALS["SessionToken"]


def test_connect_sets_connection(monkeypatch):
    """
    Test that connect() sets the connection to the role session.
    """
    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", _make_fake_session())
    ls = _make_linked_service()
    ls.connect()
    assert ls.connection is not None


def test_raises_on_assume_role_client_error(monkeypatch):
    """
    Test that connect() raises AuthorizationError when assume_role fails with ClientError.
    """
    from ds_resource_plugin_py_lib.common.resource.linked_service.errors import AuthorizationError

    def fake_session(**kwargs):
        class AmbientSession:
            def client(self, service: str):
                class StsClient:
                    def assume_role(self, **kw):
                        raise ClientError({"Error": {"Message": "Access denied", "Code": "AccessDenied"}}, "AssumeRole")

                return StsClient()

        return AmbientSession()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = _make_linked_service()
    try:
        ls.connect()
        assert False, "Expected AuthorizationError"
    except AuthorizationError as exc:
        assert "Unable to assume IAM role" in str(exc)


def test_raises_on_account_id_mismatch(monkeypatch):
    """
    Test that connect() raises AuthorizationError when the assumed role account ID does not match.
    """
    from ds_resource_plugin_py_lib.common.resource.linked_service.errors import AuthorizationError

    monkeypatch.setattr(
        "ds_provider_aws_py_lib.linked_service.aws.boto3.Session",
        _make_fake_session(account_id="999999999999"),
    )
    ls = _make_linked_service(account_id=ACCOUNT_ID)
    try:
        ls.connect()
        assert False, "Expected AuthorizationError"
    except AuthorizationError as exc:
        assert "does not match expected value" in str(exc)


def test_raises_on_get_caller_identity_error(monkeypatch):
    """
    Test that connect() raises AuthorizationError when get_caller_identity fails after assuming the role.
    """
    from ds_resource_plugin_py_lib.common.resource.linked_service.errors import AuthorizationError

    def fake_session(**kwargs):
        if kwargs.get("aws_access_key_id"):

            class RoleSession:
                def client(self, service: str):
                    class StsClient:
                        def get_caller_identity(self):
                            raise ClientError(
                                {"Error": {"Message": "STS error", "Code": "403"}}, "GetCallerIdentity"
                            )

                    return StsClient()

            return RoleSession()
        else:

            class AmbientSession:
                def client(self, service: str):
                    class StsClient:
                        def assume_role(self, **kw):
                            return {"Credentials": FAKE_CREDENTIALS}

                    return StsClient()

            return AmbientSession()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = _make_linked_service()
    try:
        ls.connect()
        assert False, "Expected AuthorizationError"
    except AuthorizationError as exc:
        assert "Unable to verify AWS account ID" in str(exc)


def test_test_connection_success(monkeypatch):
    """
    Test that test_connection() returns (True, ...) on successful role assumption.
    """
    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", _make_fake_session())
    ls = _make_linked_service()
    ok, msg = ls.test_connection()
    assert ok is True
    assert "successfully" in msg.lower()


def test_test_connection_returns_false_on_client_error(monkeypatch):
    """
    Test that test_connection() returns (False, ...) when assume_role raises ClientError.
    """

    def fake_session(**kwargs):
        class AmbientSession:
            def client(self, service: str):
                class StsClient:
                    def assume_role(self, **kw):
                        raise ClientError(
                            {"Error": {"Message": "Access denied", "Code": "AccessDenied"}}, "AssumeRole"
                        )

                return StsClient()

        return AmbientSession()

    monkeypatch.setattr("ds_provider_aws_py_lib.linked_service.aws.boto3.Session", fake_session)
    ls = _make_linked_service()
    ok, msg = ls.test_connection()
    assert ok is False
    assert "unable to assume iam role" in msg.lower()
