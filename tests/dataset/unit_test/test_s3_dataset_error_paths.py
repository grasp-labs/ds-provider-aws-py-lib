from __future__ import annotations

import io
from typing import Any, cast
from uuid import UUID

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from ds_resource_plugin_py_lib.common.resource.dataset.errors import (
    CreateError,
    ListError,
    PurgeError,
    ReadError,
    RenameError,
    UpdateError,
)
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError

from ds_provider_aws_py_lib.dataset.s3 import (
    CreateSettings,
    PurgeSettings,
    S3Dataset,
    S3DatasetSettings,
    S3UpdateStrategy,
    UpdateSettings,
)
from ds_provider_aws_py_lib.enums import ResourceType
from ds_provider_aws_py_lib.linked_service import AWSLinkedService, AWSLinkedServiceSettings

TEST_UUID = UUID("00000000-0000-0000-0000-000000000000")


class FakeSession:
    def __init__(self, client: Any) -> None:
        self._client = client

    def client(self, service: str) -> Any:
        assert service == "s3"
        return self._client


class FakeBody:
    def __init__(self, payload: Any) -> None:
        self.payload = payload

    def read(self, amt: int | None = None) -> Any:
        return self.payload


class FakePaginator:
    def __init__(self, pages: list[dict[str, Any]] | None = None, error: ClientError | None = None) -> None:
        self.pages = pages or []
        self.error = error

    def paginate(self, **kwargs: Any):
        if self.error is not None:
            raise self.error
        return iter(self.pages)


class ConfigurableS3Client:
    def __init__(
        self,
        *,
        object_exists: bool = False,
        existing_keys: set[str] | None = None,
        head_object_error: ClientError | None = None,
        head_bucket_error: ClientError | None = None,
        create_bucket_error: ClientError | None = None,
        put_object_error: ClientError | None = None,
        get_object_error: ClientError | None = None,
        get_object_payloads: dict[str, Any] | None = None,
        paginator_pages: list[dict[str, Any]] | None = None,
        paginator_error: ClientError | None = None,
        paginator_runtime_error: Exception | None = None,
        delete_objects_responses: list[dict[str, Any]] | None = None,
        delete_bucket_error: ClientError | None = None,
    ) -> None:
        self.object_exists = object_exists
        self.existing_keys = existing_keys
        self.head_object_error = head_object_error
        self.head_bucket_error = head_bucket_error
        self.create_bucket_error = create_bucket_error
        self.put_object_error = put_object_error
        self.get_object_error = get_object_error
        self.get_object_payloads = get_object_payloads or {}
        self.paginator_pages = paginator_pages or []
        self.paginator_error = paginator_error
        self.paginator_runtime_error = paginator_runtime_error
        self.delete_objects_responses = list(delete_objects_responses or [])
        self.delete_bucket_error = delete_bucket_error

        self.put_calls: list[dict[str, Any]] = []
        self.delete_objects_calls: list[dict[str, Any]] = []
        self.create_bucket_calls = 0

    def _missing_error(self, operation: str, code: str = "404", status: int = 404) -> ClientError:
        return client_error(code=code, operation=operation, status=status)

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if self.head_object_error is not None:
            raise self.head_object_error
        exists = Key in self.existing_keys if self.existing_keys is not None else self.object_exists
        if exists:
            return {"Bucket": Bucket, "Key": Key}
        raise self._missing_error("HeadObject")

    def head_bucket(self, *, Bucket: str) -> dict[str, Any]:
        if self.head_bucket_error is not None:
            raise self.head_bucket_error
        return {"Bucket": Bucket}

    def create_bucket(self, *, Bucket: str) -> dict[str, Any]:
        self.create_bucket_calls += 1
        if self.create_bucket_error is not None:
            raise self.create_bucket_error
        return {"Bucket": Bucket}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> dict[str, Any]:
        if self.put_object_error is not None:
            raise self.put_object_error
        self.put_calls.append({"Bucket": Bucket, "Key": Key, "Body": Body})
        return {"ETag": '"etag"'}

    def get_paginator(self, operation_name: str) -> FakePaginator:
        assert operation_name == "list_objects_v2"
        if self.paginator_runtime_error is not None:
            raise self.paginator_runtime_error
        return FakePaginator(self.paginator_pages, self.paginator_error)

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if self.get_object_error is not None:
            raise self.get_object_error
        payload = self.get_object_payloads.get(Key)
        if isinstance(payload, dict):
            return payload
        if payload is None:
            raise self._missing_error("GetObject", code="NoSuchKey")
        return {"Body": FakeBody(payload)}

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:
        self.delete_objects_calls.append({"Bucket": Bucket, "Delete": Delete})
        if self.delete_objects_responses:
            return self.delete_objects_responses.pop(0)
        return {"Deleted": Delete.get("Objects", [])}

    def delete_bucket(self, *, Bucket: str) -> dict[str, Any]:
        if self.delete_bucket_error is not None:
            raise self.delete_bucket_error
        return {"ResponseMetadata": {"HTTPStatusCode": 204}}


def client_error(*, code: str, operation: str, status: int = 400) -> ClientError:
    response = {
        "Error": {"Code": code, "Message": code},
        "ResponseMetadata": {"HTTPStatusCode": status},
    }
    return ClientError(cast("Any", response), operation)


def make_linked_service() -> AWSLinkedService:
    return AWSLinkedService(
        id=TEST_UUID,
        name="linked-service",
        version="1.0.0",
        settings=AWSLinkedServiceSettings(
            account_id="123456789012",
            access_key_id="AKIA_TEST",
            access_key_secret="SECRET_TEST",
            region="eu-north-1",
        ),
    )


def make_dataset(
    *,
    bucket: str | None = "bucket",
    key: str | None = "file.csv",
    create: CreateSettings | None = None,
    update: UpdateSettings | None = None,
    purge: PurgeSettings | None = None,
) -> S3Dataset:
    return S3Dataset(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        name="dataset",
        version="1.0.0",
        settings=S3DatasetSettings(
            bucket=bucket,
            key=key,
            create=create or CreateSettings(),
            update=update or UpdateSettings(),
            purge=purge or PurgeSettings(),
        ),
        linked_service=make_linked_service(),
    )


def test_type_returns_s3_resource_type() -> None:
    assert make_dataset().type == ResourceType.S3_DATASET


def test_create_helpers_cover_error_paths() -> None:
    dataset = make_dataset(create=CreateSettings(content=io.BytesIO(b"x")))
    dataset.input = pd.DataFrame({"id": [1]})
    with pytest.raises(CreateError, match=r"Both settings\.create\.content and input"):
        dataset._validate_create_sources("bucket", "file.csv")

    dataset = make_dataset()
    dataset.serializer = None
    with pytest.raises(CreateError, match="Serializer is not initialized"):
        dataset._build_create_body("bucket", "file.csv")

    dataset = make_dataset()
    dataset.serializer = lambda df: "ignored"  # type: ignore[assignment]
    dataset.input = None  # type: ignore[assignment]
    with pytest.raises(CreateError, match="Input is None"):
        dataset._build_create_body("bucket", "file.csv")

    dataset = make_dataset()
    dataset.input = pd.DataFrame({"id": [1]})

    def raising_serializer(df: pd.DataFrame) -> str:
        raise ValueError("boom")

    dataset.serializer = raising_serializer  # type: ignore[assignment]
    with pytest.raises(CreateError, match="Failed to serialize input"):
        dataset._build_create_body("bucket", "file.csv")

    dataset = make_dataset()
    dataset.input = pd.DataFrame({"id": [1]})
    dataset.serializer = lambda df: bytearray(b"abc")  # type: ignore[assignment]
    assert dataset._build_create_body("bucket", "file.csv") == b"abc"

    dataset.serializer = lambda df: 123  # type: ignore[assignment]
    with pytest.raises(CreateError, match="Unsupported serialized payload type"):
        dataset._build_create_body("bucket", "file.csv")


@pytest.mark.parametrize(
    ("key", "expected_violations"),
    [
        ("", ["empty"]),
        ("folder/", ["trailing_slash"]),
        ("reports/*.csv", ["wildcard"]),
        ("reports/file?.csv", ["wildcard"]),
        ("reports/[ab].csv", ["wildcard"]),
    ],
)
def test_validate_create_target_key_rejects_invalid_keys(key: str, expected_violations: list[str]) -> None:
    dataset = make_dataset()

    with pytest.raises(CreateError, match="requires a concrete S3 object key") as exc_info:
        dataset._validate_create_target_key("bucket", key)

    assert exc_info.value.details["bucket"] == "bucket"
    assert exc_info.value.details["key"] == key
    assert exc_info.value.details["violations"] == expected_violations


def test_validate_create_target_key_accepts_concrete_key() -> None:
    dataset = make_dataset()
    dataset._validate_create_target_key("bucket", "reports/file.csv")


def test_create_rejects_invalid_target_key_before_backend_calls() -> None:
    dataset = make_dataset(key="folder/")
    dataset.input = pd.DataFrame({"id": [1]})
    client = ConfigurableS3Client()
    dataset.linked_service._connection = FakeSession(client)

    with pytest.raises(CreateError, match="requires a concrete S3 object key"):
        dataset.create()

    assert client.create_bucket_calls == 0
    assert client.put_calls == []


def test_create_output_and_upload_and_existence_checks() -> None:
    dataset = make_dataset()
    dataset.input = None  # type: ignore[assignment]
    assert dataset._build_create_output().empty

    upload_client = ConfigurableS3Client(put_object_error=client_error(code="AccessDenied", operation="PutObject"))
    dataset.linked_service._connection = FakeSession(upload_client)
    with pytest.raises(CreateError, match="Failed to upload object to S3"):
        dataset._upload_create_body("bucket", "file.csv", b"body")

    exists_client = ConfigurableS3Client(object_exists=True)
    dataset.linked_service._connection = FakeSession(exists_client)
    with pytest.raises(CreateError, match="Target object already exists"):
        dataset._ensure_object_does_not_exist("bucket", "file.csv")

    unexpected_client = ConfigurableS3Client(head_object_error=client_error(code="500", operation="HeadObject", status=500))
    dataset.linked_service._connection = FakeSession(unexpected_client)
    with pytest.raises(CreateError, match="Unable to validate target object existence"):
        dataset._ensure_object_does_not_exist("bucket", "file.csv")


def test_ensure_bucket_exists_and_directory_marker_paths() -> None:
    dataset = make_dataset()

    # Unexpected non-missing head bucket error.
    bad_head = ConfigurableS3Client(head_bucket_error=client_error(code="403", operation="HeadBucket", status=403))
    dataset.linked_service._connection = FakeSession(bad_head)
    with pytest.raises(CreateError, match="Unable to validate S3 bucket"):
        dataset._ensure_bucket_exists("bucket")

    # Missing bucket + create disabled.
    missing_bucket = ConfigurableS3Client(head_bucket_error=client_error(code="NoSuchBucket", operation="HeadBucket", status=404))
    dataset.linked_service._connection = FakeSession(missing_bucket)
    with pytest.raises(CreateError, match="S3 bucket does not exist"):
        dataset._ensure_bucket_exists("bucket")

    # Missing bucket + create enabled + create fails.
    dataset.settings.create.create_bucket = True
    create_fails = ConfigurableS3Client(
        head_bucket_error=client_error(code="NoSuchBucket", operation="HeadBucket", status=404),
        create_bucket_error=client_error(code="BucketAlreadyExists", operation="CreateBucket", status=409),
    )
    dataset.linked_service._connection = FakeSession(create_fails)
    with pytest.raises(CreateError, match="Failed to create S3 bucket"):
        dataset._ensure_bucket_exists("bucket")

    # Directory marker creation failure is ignored.
    marker_fail = ConfigurableS3Client(put_object_error=client_error(code="AccessDenied", operation="PutObject", status=403))
    dataset.linked_service._connection = FakeSession(marker_fail)
    dataset._ensure_directory_exists("bucket", "dir/file.csv")


def test_read_helpers_cover_object_and_wildcard_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = make_dataset(key="file.csv")
    object_client = ConfigurableS3Client(object_exists=True, get_object_payloads={"file.csv": b"id\n1\n"})
    dataset.linked_service._connection = FakeSession(object_client)
    dataset.read()
    assert list(dataset.output["id"]) == [1]

    assert dataset._wildcard_list_prefix("reports/*.csv") == "reports/"
    assert dataset._wildcard_list_prefix("reports.csv") == "reports.csv"
    assert dataset._wildcard_list_prefix("*.csv") == ""

    wildcard_client = ConfigurableS3Client(
        paginator_pages=[{"Contents": [{"Key": None}, {"Key": "reports/"}, {"Key": "reports/b.csv"}, {"Key": "reports/a.csv"}]}]
    )
    assert dataset._list_matching_keys(cast("Any", wildcard_client), "bucket", "reports/*.csv") == [
        "reports/a.csv",
        "reports/b.csv",
    ]

    failing_list_client = ConfigurableS3Client(
        paginator_error=client_error(code="AccessDenied", operation="ListObjectsV2", status=403)
    )
    with pytest.raises(ReadError, match="Failed to list objects for wildcard"):
        dataset._list_matching_keys(cast("Any", failing_list_client), "bucket", "reports/*.csv")

    dataset.deserializer = lambda raw: (_ for _ in ()).throw(ValueError("bad"))  # type: ignore[assignment]
    with pytest.raises(ReadError, match="Failed to deserialize S3 object in wildcard read"):
        dataset._read_wildcard(
            cast(
                "Any",
                ConfigurableS3Client(
                    paginator_pages=[{"Contents": [{"Key": "reports/a.csv"}]}],
                    get_object_payloads={"reports/a.csv": b"id\n1\n"},
                ),
            ),
            "bucket",
            "reports/*.csv",
            cast("Any", dataset.deserializer),
        )

    dataset.deserializer = None
    with pytest.raises(ReadError, match="Deserializer is not initialized"):
        dataset.check_deserializer_exist()

    with pytest.raises(ReadError, match="S3 bucket must be provided"):
        make_dataset(bucket=None)._resolve_bucket_key(ReadError)
    with pytest.raises(ReadError, match="S3 key must be provided"):
        make_dataset(key=None)._resolve_bucket_key(ReadError)

    assert make_dataset(bucket=None)._current_s3_uri() is None
    assert make_dataset(bucket="bucket", key=None)._current_s3_uri() is None

    with pytest.raises(ReadError, match="Failed to check S3 object existence"):
        dataset._is_object(
            cast("Any", ConfigurableS3Client(head_object_error=client_error(code="403", operation="HeadObject", status=403))),
            "bucket",
            "file.csv",
        )

    dataset = make_dataset()
    dataset.linked_service._connection = FakeSession(
        ConfigurableS3Client(
            paginator_pages=[{"Contents": [{"Key": "reports/a.csv"}]}],
            get_object_payloads={"reports/a.csv": b"id\n1\n"},
        )
    )
    dataset.deserializer = lambda raw: (_ for _ in ()).throw(ValueError("bad"))  # type: ignore[assignment]
    with pytest.raises(ReadError, match="Failed to deserialize S3 object in prefix"):
        dataset._read_prefix(dataset._get_s3_client(ReadError), "bucket", "reports")

    dataset.deserializer = cast("Any", lambda raw: pd.read_csv(io.BytesIO(raw)))
    with pytest.raises(ReadError, match="Failed to list objects in S3 prefix"):
        dataset._read_prefix(
            cast(
                "Any",
                ConfigurableS3Client(paginator_error=client_error(code="AccessDenied", operation="ListObjectsV2", status=403)),
            ),
            "bucket",
            "reports",
        )

    dataset = make_dataset()
    dataset.deserializer = cast("Any", lambda raw: pd.read_csv(io.BytesIO(raw)))
    with monkeypatch.context() as m:
        m.setattr(pd, "concat", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("concat")))
        with pytest.raises(ReadError, match="Failed to concatenate dataframes from wildcard"):
            dataset._read_wildcard(
                cast(
                    "Any",
                    ConfigurableS3Client(
                        paginator_pages=[{"Contents": [{"Key": "reports/a.csv"}, {"Key": "reports/b.csv"}]}],
                        get_object_payloads={"reports/a.csv": b"id\n1\n", "reports/b.csv": b"id\n2\n"},
                    ),
                ),
                "bucket",
                "reports/*.csv",
                cast("Any", dataset.deserializer),
            )
        with pytest.raises(ReadError, match="Failed to concatenate dataframes from S3 prefix"):
            dataset._read_prefix(
                cast(
                    "Any",
                    ConfigurableS3Client(
                        paginator_pages=[{"Contents": [{"Key": "reports/a.csv"}, {"Key": "reports/b.csv"}]}],
                        get_object_payloads={"reports/a.csv": b"id\n1\n", "reports/b.csv": b"id\n2\n"},
                    ),
                ),
                "bucket",
                "reports",
            )


def test_read_object_and_delete_cover_error_paths() -> None:
    with pytest.raises(ReadError, match="S3 object has no body"):
        S3Dataset._read_object(
            cast("Any", ConfigurableS3Client(get_object_payloads={"file.csv": {}})),
            "bucket",
            "file.csv",
        )

    with pytest.raises(ReadError, match="unsupported payload type"):
        S3Dataset._read_object(
            cast("Any", ConfigurableS3Client(get_object_payloads={"file.csv": "not-bytes"})),
            "bucket",
            "file.csv",
        )

    with pytest.raises(ReadError, match="Failed to read object from S3"):
        S3Dataset._read_object(
            cast(
                "Any",
                ConfigurableS3Client(get_object_error=client_error(code="AccessDenied", operation="GetObject", status=403)),
            ),
            "bucket",
            "file.csv",
        )

    with pytest.raises(NotSupportedError):
        make_dataset().delete()


def test_update_rejects_unknown_strategy() -> None:
    dataset = make_dataset(update=UpdateSettings(strategy="mystery"))
    dataset.input = pd.DataFrame({"id": [1]})
    dataset.linked_service._connection = FakeSession(ConfigurableS3Client(object_exists=True))

    with pytest.raises(UpdateError, match="Unknown update strategy"):
        dataset.update()


def test_update_build_output_and_source_validation_errors() -> None:
    dataset = make_dataset()
    dataset.input = None  # type: ignore[assignment]
    assert dataset._build_update_output().empty

    dataset = make_dataset(update=UpdateSettings(content=io.BytesIO(b"x"), strategy=S3UpdateStrategy.OVERWRITE))
    dataset.input = pd.DataFrame({"id": [1]})

    with pytest.raises(UpdateError, match=r"Both settings\.update\.content and input"):
        dataset._validate_update_sources("bucket", "file.csv")


def test_update_overwrite_helper_errors() -> None:
    dataset = make_dataset()
    dataset.linked_service._connection = FakeSession(
        ConfigurableS3Client(head_object_error=client_error(code="403", operation="HeadObject", status=403))
    )
    with pytest.raises(UpdateError, match="Unable to validate target object existence"):
        dataset._ensure_object_exists("bucket", "file.csv")

    dataset = make_dataset()
    dataset.serializer = None
    with pytest.raises(UpdateError, match="Serializer is not initialized"):
        dataset._build_update_body("bucket", "file.csv")

    dataset = make_dataset()
    dataset.input = None  # type: ignore[assignment]
    with pytest.raises(UpdateError, match="Input is None"):
        dataset._build_update_body("bucket", "file.csv")

    dataset = make_dataset()
    dataset.input = pd.DataFrame({"id": [1]})

    def bad_serializer(df: pd.DataFrame) -> str:
        raise ValueError("boom")

    dataset.serializer = bad_serializer  # type: ignore[assignment]
    with pytest.raises(UpdateError, match="Failed to serialize input"):
        dataset._build_update_body("bucket", "file.csv")

    dataset.serializer = lambda df: object()  # type: ignore[assignment]
    with pytest.raises(UpdateError, match="Unsupported serialized payload type"):
        dataset._build_update_body("bucket", "file.csv")


def test_update_append_download_and_deserialize_errors() -> None:
    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.APPEND))
    dataset.input = pd.DataFrame({"id": [2]})
    dataset.linked_service._connection = FakeSession(
        ConfigurableS3Client(get_object_error=client_error(code="AccessDenied", operation="GetObject", status=403))
    )
    with pytest.raises(UpdateError, match="Failed to download existing object for APPEND"):
        dataset._build_append_body("bucket", "file.csv")

    dataset.linked_service._connection = FakeSession(ConfigurableS3Client(get_object_payloads={"file.csv": b"id\n1\n"}))
    dataset.deserializer = lambda raw: (_ for _ in ()).throw(ValueError("bad"))  # type: ignore[assignment]
    with pytest.raises(UpdateError, match="Failed to deserialize existing S3 object for APPEND"):
        dataset._build_append_body("bucket", "file.csv")


def test_update_append_input_concat_and_serialize_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.APPEND))
    dataset.input = None  # type: ignore[assignment]
    dataset.linked_service._connection = FakeSession(ConfigurableS3Client(get_object_payloads={"file.csv": b"id\n1\n"}))
    with pytest.raises(UpdateError, match="APPEND strategy requires input DataFrame"):
        dataset._build_append_body("bucket", "file.csv")

    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.APPEND))
    dataset.input = pd.DataFrame({"id": [2]})
    dataset.linked_service._connection = FakeSession(ConfigurableS3Client(get_object_payloads={"file.csv": b"id\n1\n"}))
    with monkeypatch.context() as m:
        m.setattr(pd, "concat", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("concat")))
        with pytest.raises(UpdateError, match="Failed to concatenate existing and new DataFrames"):
            dataset._build_append_body("bucket", "file.csv")

    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.APPEND))
    dataset.input = pd.DataFrame({"id": [2]})
    dataset.linked_service._connection = FakeSession(ConfigurableS3Client(get_object_payloads={"file.csv": b"id\n1\n"}))
    dataset.serializer = lambda df: (_ for _ in ()).throw(ValueError("bad"))  # type: ignore[assignment]
    with pytest.raises(UpdateError, match="Failed to serialize combined DataFrame for APPEND"):
        dataset._build_append_body("bucket", "file.csv")

    dataset.serializer = lambda df: object()  # type: ignore[assignment]
    with pytest.raises(UpdateError, match="Unsupported serialized payload type for S3 APPEND upload"):
        dataset._build_append_body("bucket", "file.csv")


def test_update_upload_wraps_put_object_client_error() -> None:
    dataset = make_dataset()
    dataset.linked_service._connection = FakeSession(
        ConfigurableS3Client(put_object_error=client_error(code="AccessDenied", operation="PutObject", status=403))
    )
    with pytest.raises(UpdateError, match="Failed to overwrite object in S3"):
        dataset._upload_update_body("bucket", "file.csv", b"payload")


def test_purge_and_static_helpers_cover_branches() -> None:
    dataset = make_dataset(key="", purge=PurgeSettings(remove_bucket=False))
    dataset.linked_service._connection = FakeSession(ConfigurableS3Client())
    with pytest.raises(PurgeError, match="Bucket purge is disabled"):
        dataset.purge()

    bucket_client = ConfigurableS3Client(
        paginator_pages=[{"Contents": [{"Key": "a.csv"}, {"Key": "b.csv"}]}],
        delete_objects_responses=[{"Deleted": [{"Key": "a.csv"}, {"Key": "b.csv"}]}],
    )
    dataset = make_dataset(key="", purge=PurgeSettings(remove_bucket=True))
    dataset.linked_service._connection = FakeSession(bucket_client)
    dataset.purge()
    assert dataset.output.iloc[0]["purge_scope"] == "bucket"

    no_bucket_client = ConfigurableS3Client(
        paginator_pages=[{"Contents": []}],
        delete_bucket_error=client_error(code="NoSuchBucket", operation="DeleteBucket", status=404),
    )
    dataset = make_dataset(key="", purge=PurgeSettings(remove_bucket=True))
    dataset.linked_service._connection = FakeSession(no_bucket_client)
    dataset.purge()
    assert dataset.output.iloc[0]["delete_bucket_response"] is None

    client_error_client = ConfigurableS3Client(
        paginator_error=client_error(code="AccessDenied", operation="ListObjectsV2", status=403)
    )
    dataset = make_dataset(key="prefix")
    dataset.linked_service._connection = FakeSession(client_error_client)
    with pytest.raises(PurgeError, match="Failed to purge S3 path"):
        dataset.purge()

    runtime_error_client = ConfigurableS3Client(paginator_runtime_error=RuntimeError("boom"))
    dataset = make_dataset(key="prefix")
    dataset.linked_service._connection = FakeSession(runtime_error_client)
    with pytest.raises(PurgeError, match="Unexpected purge failure"):
        dataset.purge()

    keys = S3Dataset._list_keys_for_prefix(
        cast("Any", ConfigurableS3Client(paginator_pages=[{"Contents": [{"Key": "a"}, {"Key": None}, {"Key": "b"}]}])),
        "bucket",
        "",
    )
    assert keys == ["a", "b"]

    assert (
        S3Dataset._list_keys_for_prefix(
            cast(
                "Any",
                ConfigurableS3Client(paginator_error=client_error(code="NoSuchBucket", operation="ListObjectsV2", status=404)),
            ),
            "bucket",
            "",
        )
        == []
    )

    with pytest.raises(ClientError):
        S3Dataset._list_keys_for_prefix(
            cast(
                "Any",
                ConfigurableS3Client(paginator_error=client_error(code="AccessDenied", operation="ListObjectsV2", status=403)),
            ),
            "bucket",
            "",
        )

    assert S3Dataset._delete_keys(cast("Any", ConfigurableS3Client()), "bucket", []) == []

    many_keys = [f"k-{idx}" for idx in range(1001)]
    batch_client = ConfigurableS3Client(
        delete_objects_responses=[{"Deleted": []}, {"Deleted": []}],
    )
    responses = S3Dataset._delete_keys(cast("Any", batch_client), "bucket", many_keys)
    assert len(responses) == 2
    assert len(batch_client.delete_objects_calls) == 2

    with pytest.raises(PurgeError, match="Failed to delete one or more S3 objects"):
        S3Dataset._delete_keys(
            cast("Any", ConfigurableS3Client(delete_objects_responses=[{"Errors": [{"Key": "bad"}]}])),
            "bucket",
            ["bad"],
        )


def test_list_skips_directory_entries_and_non_matching_wildcard() -> None:
    client = ConfigurableS3Client(
        paginator_pages=[
            {
                "Contents": [
                    {"Key": "reports/"},
                    {"Key": "reports/a.txt", "Size": 1},
                    {"Key": "reports/a.csv", "Size": 2},
                ]
            }
        ],
        get_object_payloads={"reports/a.csv": b"id\n1\n"},
    )
    dataset = make_dataset(key="reports/*.csv")
    dataset.linked_service._connection = FakeSession(client)

    dataset.list()

    assert len(dataset.output) == 1
    assert dataset.output.iloc[0]["metadata"]["key"] == "reports/a.csv"


def test_directory_prefix_helpers_and_update_bytes_branches() -> None:
    dataset = make_dataset()
    client = ConfigurableS3Client()
    dataset.linked_service._connection = FakeSession(client)

    # Covers early return when directory part is empty after strip().
    dataset._ensure_directory_exists("bucket", "/file.csv")
    assert client.put_calls == []

    # Covers prefix listing skip for directory marker keys.
    dataset.deserializer = cast("Any", lambda raw: pd.read_csv(io.BytesIO(raw)))
    prefix_client = ConfigurableS3Client(
        paginator_pages=[{"Contents": [{"Key": "reports/"}, {"Key": "reports/a.csv"}]}],
        get_object_payloads={"reports/a.csv": b"id\n1\n"},
    )
    df = dataset._read_prefix(cast("Any", prefix_client), "bucket", "reports")
    assert list(df["id"]) == [1]

    # Covers bytearray->bytes branch in overwrite body builder.
    dataset.input = pd.DataFrame({"id": [1]})
    dataset.serializer = lambda df: bytearray(b"overwrite")  # type: ignore[assignment]
    assert dataset._build_update_body("bucket", "file.csv") == b"overwrite"

    # Covers bytearray->bytes branch in append body builder.
    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.APPEND))
    dataset.linked_service._connection = FakeSession(ConfigurableS3Client(get_object_payloads={"file.csv": b"id\n1\n"}))
    dataset.input = pd.DataFrame({"id": [2]})
    dataset.serializer = lambda df: bytearray(b"append")  # type: ignore[assignment]
    assert dataset._build_append_body("bucket", "file.csv") == b"append"


def test_purge_object_prefix_and_delete_bucket_error_paths() -> None:
    # Covers object scope branch (keys=[key], purge_scope="object").
    object_client = ConfigurableS3Client(
        object_exists=True,
        delete_objects_responses=[{"Deleted": [{"Key": "file.csv"}]}],
    )
    dataset = make_dataset(key="file.csv")
    dataset.linked_service._connection = FakeSession(object_client)
    dataset.purge()
    assert dataset.output.iloc[0]["purge_scope"] == "object"
    assert dataset.output.iloc[0]["deleted_keys"] == ["file.csv"]

    # Covers prefix scope/output branch.
    prefix_client = ConfigurableS3Client(
        object_exists=False,
        paginator_pages=[{"Contents": [{"Key": "dir/a.csv"}, {"Key": "dir/b.csv"}]}],
        delete_objects_responses=[{"Deleted": [{"Key": "dir/a.csv"}, {"Key": "dir/b.csv"}]}],
    )
    dataset = make_dataset(key="dir")
    dataset.linked_service._connection = FakeSession(prefix_client)
    dataset.purge()
    assert dataset.output.iloc[0]["purge_scope"] == "prefix"
    assert dataset.output.iloc[0]["deleted_keys"] == ["dir/a.csv", "dir/b.csv"]

    # Covers inner delete_bucket re-raise branch, then outer ClientError->PurgeError wrapper.
    error_client = ConfigurableS3Client(
        paginator_pages=[{"Contents": []}],
        delete_bucket_error=client_error(code="AccessDenied", operation="DeleteBucket", status=403),
    )
    dataset = make_dataset(key="", purge=PurgeSettings(remove_bucket=True))
    dataset.linked_service._connection = FakeSession(error_client)
    with pytest.raises(PurgeError, match="Failed to purge S3 path"):
        dataset.purge()


def test_list_wraps_read_and_list_client_errors() -> None:
    # Covers ReadError->ListError wrapping while downloading object content.
    read_fail_client = ConfigurableS3Client(
        paginator_pages=[{"Contents": [{"Key": "reports/a.csv", "Size": 1}]}],
        get_object_payloads={"reports/a.csv": "not-bytes"},
    )
    dataset = make_dataset(key="reports/")
    dataset.linked_service._connection = FakeSession(read_fail_client)
    with pytest.raises(ListError, match="Failed to read object content while listing"):
        dataset.list()

    # Covers paginator ClientError->ListError wrapping.
    list_fail_client = ConfigurableS3Client(
        paginator_error=client_error(code="AccessDenied", operation="ListObjectsV2", status=403)
    )
    dataset = make_dataset(key="reports/")
    dataset.linked_service._connection = FakeSession(list_fail_client)
    with pytest.raises(ListError, match="Failed to list objects in S3"):
        dataset.list()


def test_rename_guards_helpers_and_not_supported_methods() -> None:
    dataset = make_dataset(key="*.csv")
    dataset.settings.rename.new_file_path = "new.csv"
    with pytest.raises(RenameError, match="does not support wildcard"):
        dataset.rename()

    dataset = make_dataset(key="same.csv")
    dataset.settings.rename.new_file_path = "same.csv"
    with pytest.raises(RenameError, match="must be different"):
        dataset.rename()

    with pytest.raises(RenameError, match="Unable to validate source object"):
        S3Dataset._ensure_object_exists_for_rename(
            cast(
                "Any",
                ConfigurableS3Client(head_object_error=client_error(code="AccessDenied", operation="HeadObject", status=403)),
            ),
            "bucket",
            "old.csv",
        )

    with pytest.raises(RenameError, match="Unable to validate destination object"):
        S3Dataset._ensure_object_absent_for_rename(
            cast(
                "Any",
                ConfigurableS3Client(head_object_error=client_error(code="AccessDenied", operation="HeadObject", status=403)),
            ),
            "bucket",
            "new.csv",
        )

    with pytest.raises(NotSupportedError):
        make_dataset().upsert()


def test_close_delegates_to_linked_service_close() -> None:
    dataset = make_dataset()
    calls: dict[str, int] = {"close": 0}

    def close_spy() -> None:
        calls["close"] += 1

    dataset.linked_service.close = close_spy  # type: ignore[assignment]
    dataset.close()
    assert calls["close"] == 1
