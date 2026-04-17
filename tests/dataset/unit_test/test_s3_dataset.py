from __future__ import annotations

import io
from typing import Any, cast
from uuid import UUID

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from ds_resource_plugin_py_lib.common.resource.dataset.errors import CreateError, ListError, ReadError, RenameError, UpdateError

from ds_provider_aws_py_lib.dataset.s3 import (
    CreateSettings,
    ListSettings,
    RenameSettings,
    S3Dataset,
    S3DatasetSettings,
    S3UpdateStrategy,
    UpdateSettings,
)
from ds_provider_aws_py_lib.linked_service import AWSLinkedService, AWSLinkedServiceSettings

TEST_UUID = UUID("00000000-0000-0000-0000-000000000000")


class CloseTracker:
    def __init__(self) -> None:
        self.calls = 0

    def close(self) -> None:
        self.calls += 1


class FakeSession:
    def __init__(self, client=None, close_tracker: CloseTracker | None = None) -> None:
        self._client = client
        self._session = close_tracker

    def client(self, service: str):
        assert service == "s3"
        return self._client


class FakePaginator:
    def __init__(self, pages: list[dict]) -> None:
        self.pages = pages

    def paginate(self, **kwargs):
        return iter(self.pages)


class FakeS3Client:
    def __init__(
        self,
        *,
        object_exists: bool = False,
        pages: list[dict] | None = None,
        bodies: dict[str, bytes] | None = None,
        existing_keys: set[str] | None = None,
        fail_on_copy: bool = False,
        fail_on_delete: bool = False,
    ):
        self.object_exists = object_exists
        self.pages = pages or []
        self.bodies = bodies or {}
        self.existing_keys = existing_keys
        self.fail_on_copy = fail_on_copy
        self.fail_on_delete = fail_on_delete
        self.put_calls: list[dict] = []
        self.copy_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self.get_object_calls: list[dict] = []

    def head_bucket(self, Bucket: str) -> dict:
        return {"Bucket": Bucket}

    def create_bucket(self, Bucket: str) -> dict:
        return {"Bucket": Bucket}

    def head_object(self, Bucket: str, Key: str) -> dict:
        exists = Key in self.existing_keys if self.existing_keys is not None else self.object_exists

        if exists:
            return {"Bucket": Bucket, "Key": Key}
        error_response = cast(
            "dict[str, Any]",
            {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
        )
        raise ClientError(error_response, "HeadObject")  # type: ignore[arg-type]

    def put_object(self, **kwargs) -> dict:
        self.put_calls.append(kwargs)
        return {"ETag": '"etag"'}

    def get_paginator(self, name: str) -> FakePaginator:
        assert name == "list_objects_v2"
        return FakePaginator(self.pages)

    def get_object(self, Bucket: str, Key: str) -> dict:
        self.get_object_calls.append({"Bucket": Bucket, "Key": Key})
        return {"Body": io.BytesIO(self.bodies[Key])}

    def copy_object(self, *, Bucket: str, Key: str, CopySource: dict[str, str]) -> dict:
        if self.fail_on_copy:
            error_response = cast("dict[str, Any]", {"Error": {"Code": "AccessDenied"}})
            raise ClientError(error_response, "CopyObject")  # type: ignore[arg-type]
        self.copy_calls.append({"Bucket": Bucket, "Key": Key, "CopySource": CopySource})
        if self.existing_keys is not None:
            self.existing_keys.add(Key)
        return {"CopyObjectResult": {"ETag": '"copied"'}}

    def delete_object(self, *, Bucket: str, Key: str) -> dict:
        if self.fail_on_delete:
            error_response = cast("dict[str, Any]", {"Error": {"Code": "AccessDenied"}})
            raise ClientError(error_response, "DeleteObject")  # type: ignore[arg-type]
        self.delete_calls.append({"Bucket": Bucket, "Key": Key})
        if self.existing_keys is not None:
            self.existing_keys.discard(Key)
        return {}


def make_linked_service() -> AWSLinkedService:
    return AWSLinkedService(
        id=TEST_UUID,
        name="test-linked-service",
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
    bucket: str = "bucket",
    key: str = "file.csv",
    create: CreateSettings | None = None,
    update: UpdateSettings | None = None,
    rename: RenameSettings | None = None,
    list_settings: ListSettings | None = None,
) -> S3Dataset:
    return S3Dataset(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        name="test-s3-dataset",
        version="1.0.0",
        settings=S3DatasetSettings(
            bucket=bucket,
            key=key,
            create=create or CreateSettings(),
            update=update or UpdateSettings(),
            rename=rename or RenameSettings(),
            list=list_settings or ListSettings(),
        ),
        linked_service=make_linked_service(),
    )


def test_create_noops_for_none_input_without_contacting_backend():
    dataset = make_dataset()

    dataset.create()

    assert isinstance(dataset.output, pd.DataFrame)
    assert dataset.output.empty


def test_create_wraps_missing_connection_as_create_error():
    dataset = make_dataset()
    dataset.input = pd.DataFrame({"id": [1]})

    with pytest.raises(CreateError, match="Unable to acquire S3 client"):
        dataset.create()


def test_create_uses_aws_response_as_output_for_s3_writes():
    client = FakeS3Client()
    dataset = make_dataset()
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.input = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})

    dataset.create()

    assert list(dataset.output.columns) == ["ETag"]
    assert dataset.output.iloc[0]["ETag"] == '"etag"'
    assert len(client.put_calls) == 1
    assert client.put_calls[0]["Bucket"] == "bucket"
    assert client.put_calls[0]["Key"] == "file.csv"


def test_create_with_content_only_uses_aws_response_as_output():
    client = FakeS3Client()
    dataset = make_dataset(create=CreateSettings(content=io.BytesIO(b"hello,s3\n")))
    dataset.linked_service._connection = FakeSession(client=client)

    dataset.create()

    assert list(dataset.output.columns) == ["ETag"]
    assert dataset.output.iloc[0]["ETag"] == '"etag"'
    assert client.put_calls[0]["Body"] == b"hello,s3\n"


def test_list_wraps_missing_connection_as_list_error():
    dataset = make_dataset(key="")

    with pytest.raises(ListError, match="Unable to acquire S3 client"):
        dataset.list()


def test_list_downloads_content_by_default():
    pages = [{"Contents": [{"Key": "reports/a.csv", "Size": 10}]}]
    bodies = {"reports/a.csv": b"id,name\n1,Alice\n"}
    client = FakeS3Client(pages=pages, bodies=bodies)
    dataset = make_dataset(key="reports/")
    dataset.linked_service._connection = FakeSession(client=client)

    dataset.list()

    assert len(client.get_object_calls) == 1
    assert list(dataset.output.columns) == ["metadata", "content"]
    assert dataset.output.iloc[0]["content"] == b"id,name\n1,Alice\n"
    metadata = dataset.output.iloc[0]["metadata"]
    assert metadata["key"] == "reports/a.csv"
    assert metadata["path"] == "s3://bucket/reports/a.csv"


def test_list_without_download_file_returns_metadata_only():
    pages = [{"Contents": [{"Key": "reports/a.csv", "Size": 10}]}]
    client = FakeS3Client(pages=pages, bodies={})
    dataset = make_dataset(key="reports/", list_settings=ListSettings(download_file=False))
    dataset.linked_service._connection = FakeSession(client=client)

    dataset.list()

    assert len(client.get_object_calls) == 0
    assert list(dataset.output.columns) == ["metadata"]
    assert "content" not in dataset.output.columns
    metadata = dataset.output.iloc[0]["metadata"]
    assert metadata["key"] == "reports/a.csv"


def test_read_supports_wildcard_pattern_and_concatenates_matches():
    pages = [
        {
            "Contents": [
                {"Key": "reports/a.csv"},
                {"Key": "reports/b.csv"},
                {"Key": "reports/readme.txt"},
            ]
        }
    ]
    bodies = {
        "reports/a.csv": b"id,name\n1,Alice\n",
        "reports/b.csv": b"id,name\n2,Bob\n",
        "reports/readme.txt": b"ignored",
    }
    client = FakeS3Client(pages=pages, bodies=bodies)
    dataset = make_dataset(key="reports/*.csv")
    dataset.linked_service._connection = FakeSession(client=client)

    dataset.read()

    assert list(dataset.output["id"]) == [1, 2]
    assert list(dataset.output["name"]) == ["Alice", "Bob"]


def test_read_wildcard_with_no_matches_raises_read_error():
    pages = [{"Contents": [{"Key": "reports/readme.txt"}]}]
    bodies = {"reports/readme.txt": b"ignored"}
    client = FakeS3Client(pages=pages, bodies=bodies)
    dataset = make_dataset(key="reports/*.csv")
    dataset.linked_service._connection = FakeSession(client=client)

    with pytest.raises(ReadError, match="No objects matched wildcard S3 pattern"):
        dataset.read()


def test_read_prefix_with_no_matches_raises_read_error():
    pages = [{"Contents": []}]
    client = FakeS3Client(pages=pages, bodies={})
    dataset = make_dataset(key="reports")
    dataset.linked_service._connection = FakeSession(client=client)

    with pytest.raises(ReadError, match="No objects found matching S3 prefix"):
        dataset.read()


# ---------------------------------------------------------------------------
# update() - OVERWRITE strategy (default)
# ---------------------------------------------------------------------------


def test_update_overwrite_replaces_existing_object():
    client = FakeS3Client(object_exists=True)
    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.OVERWRITE))
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.input = pd.DataFrame({"id": [99], "name": ["Updated"]})

    dataset.update()

    assert len(client.put_calls) == 1
    assert client.put_calls[0]["Bucket"] == "bucket"
    assert client.put_calls[0]["Key"] == "file.csv"
    assert list(dataset.output.columns) == ["ETag"]
    assert dataset.output.iloc[0]["ETag"] == '"etag"'


def test_update_overwrite_noops_for_empty_input():
    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.OVERWRITE))
    # no linked service set up on purpose — should never contact backend

    dataset.update()

    assert isinstance(dataset.output, pd.DataFrame)
    assert dataset.output.empty


def test_update_overwrite_raises_update_error_when_object_missing():
    client = FakeS3Client(object_exists=False)
    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.OVERWRITE))
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.input = pd.DataFrame({"id": [1]})

    with pytest.raises(UpdateError, match="Target object does not exist"):
        dataset.update()


def test_update_overwrite_with_content_replaces_existing_object():
    client = FakeS3Client(object_exists=True)
    payload = b"id,name\n10,FromContent\n"
    dataset = make_dataset(
        update=UpdateSettings(content=io.BytesIO(payload), strategy=S3UpdateStrategy.OVERWRITE),
    )
    dataset.linked_service._connection = FakeSession(client=client)

    dataset.update()

    assert len(client.put_calls) == 1
    assert client.put_calls[0]["Body"] == payload
    assert list(dataset.output.columns) == ["ETag"]
    assert dataset.output.iloc[0]["ETag"] == '"etag"'


# ---------------------------------------------------------------------------
# update() - APPEND strategy
# ---------------------------------------------------------------------------


def test_update_append_concatenates_rows():
    existing_csv = b"id,name\n1,Alice\n"
    client = FakeS3Client(object_exists=True, bodies={"file.csv": existing_csv})
    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.APPEND))
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.input = pd.DataFrame({"id": [2], "name": ["Bob"]})

    dataset.update()

    # Exactly one put_object call (overwrite with combined content)
    assert len(client.put_calls) == 1
    uploaded_bytes = client.put_calls[0]["Body"]
    result = pd.read_csv(io.BytesIO(uploaded_bytes))
    assert list(result["id"]) == [1, 2]
    assert list(result["name"]) == ["Alice", "Bob"]
    assert list(dataset.output.columns) == ["ETag"]
    assert dataset.output.iloc[0]["ETag"] == '"etag"'


def test_update_append_with_content_raises_update_error():
    client = FakeS3Client(object_exists=True, bodies={"file.csv": b"id,name\n1,Alice\n"})
    dataset = make_dataset(
        update=UpdateSettings(content=io.BytesIO(b"id,name\n2,Bob\n"), strategy=S3UpdateStrategy.APPEND),
    )
    dataset.linked_service._connection = FakeSession(client=client)

    with pytest.raises(UpdateError, match=r"settings\.update\.content is supported only for OVERWRITE"):
        dataset.update()


def test_update_append_raises_update_error_when_deserializer_missing():
    client = FakeS3Client(object_exists=True, bodies={"file.csv": b"id\n1\n"})
    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.APPEND))
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.deserializer = None
    dataset.input = pd.DataFrame({"id": [2]})

    with pytest.raises(UpdateError, match="Deserializer is not initialized"):
        dataset.update()


def test_update_append_raises_update_error_when_serializer_missing():
    client = FakeS3Client(object_exists=True, bodies={"file.csv": b"id\n1\n"})
    dataset = make_dataset(update=UpdateSettings(strategy=S3UpdateStrategy.APPEND))
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.serializer = None
    dataset.input = pd.DataFrame({"id": [2]})

    with pytest.raises(UpdateError, match="Serializer is not initialized"):
        dataset.update()


def test_update_strategy_enum_values():
    assert S3UpdateStrategy.OVERWRITE == "overwrite"
    assert S3UpdateStrategy.APPEND == "append"


def test_update_default_strategy_is_overwrite():
    settings = S3DatasetSettings(bucket="bucket", key="file.csv")
    assert settings.update.strategy == "overwrite"


def test_rename_moves_object_using_copy_then_delete():
    client = FakeS3Client(existing_keys={"old.csv"})
    dataset = make_dataset(bucket="bucket", key="old.csv", rename=RenameSettings(new_file_path="new.csv"))
    dataset.linked_service._connection = FakeSession(client=client)

    dataset.rename()

    assert len(client.copy_calls) == 1
    assert client.copy_calls[0]["Key"] == "new.csv"
    assert client.copy_calls[0]["CopySource"] == {"Bucket": "bucket", "Key": "old.csv"}
    assert len(client.delete_calls) == 1
    assert client.delete_calls[0]["Key"] == "old.csv"
    assert list(dataset.output.columns) == ["copy_response", "delete_response", "source", "target"]
    assert dataset.output.iloc[0]["copy_response"] == {"CopyObjectResult": {"ETag": '"copied"'}}
    assert dataset.output.iloc[0]["delete_response"] == {}
    assert dataset.output.iloc[0]["source"] == "s3://bucket/old.csv"
    assert dataset.output.iloc[0]["target"] == "s3://bucket/new.csv"


def test_rename_requires_new_path():
    dataset = make_dataset(bucket="bucket", key="old.csv")

    with pytest.raises(RenameError, match=r"settings\.rename\.new_file_path must be provided"):
        dataset.rename()


def test_rename_raises_when_source_missing():
    client = FakeS3Client(existing_keys=set())
    dataset = make_dataset(bucket="bucket", key="missing.csv", rename=RenameSettings(new_file_path="new.csv"))
    dataset.linked_service._connection = FakeSession(client=client)

    with pytest.raises(RenameError, match="Source object does not exist"):
        dataset.rename()


def test_rename_raises_when_destination_exists():
    client = FakeS3Client(existing_keys={"old.csv", "new.csv"})
    dataset = make_dataset(bucket="bucket", key="old.csv", rename=RenameSettings(new_file_path="new.csv"))
    dataset.linked_service._connection = FakeSession(client=client)

    with pytest.raises(RenameError, match="Destination object already exists"):
        dataset.rename()


def test_rename_wraps_copy_failure_as_rename_error():
    client = FakeS3Client(existing_keys={"old.csv"}, fail_on_copy=True)
    dataset = make_dataset(bucket="bucket", key="old.csv", rename=RenameSettings(new_file_path="new.csv"))
    dataset.linked_service._connection = FakeSession(client=client)

    with pytest.raises(RenameError, match="Failed to rename S3 object"):
        dataset.rename()
