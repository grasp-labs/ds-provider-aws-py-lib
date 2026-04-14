from __future__ import annotations

import io
from typing import Any, cast
from uuid import UUID

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from ds_resource_plugin_py_lib.common.resource.dataset.errors import CreateError, ListError, ReadError, UpdateError

from ds_provider_aws_py_lib.dataset import S3Dataset, S3DatasetSettings, S3UpdateStrategy
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
    def __init__(self, *, object_exists: bool = False, pages: list[dict] | None = None, bodies: dict[str, bytes] | None = None):
        self.object_exists = object_exists
        self.pages = pages or []
        self.bodies = bodies or {}
        self.put_calls: list[dict] = []

    def head_bucket(self, Bucket: str) -> dict:
        return {"Bucket": Bucket}

    def create_bucket(self, Bucket: str) -> dict:
        return {"Bucket": Bucket}

    def head_object(self, Bucket: str, Key: str) -> dict:
        if self.object_exists:
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
        return {"Body": io.BytesIO(self.bodies[Key])}


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
    path: str = "s3://bucket/file.csv",
    content: io.BytesIO | None = None,
    update_strategy: S3UpdateStrategy = S3UpdateStrategy.OVERWRITE,
) -> S3Dataset:
    return S3Dataset(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        name="test-s3-dataset",
        version="1.0.0",
        settings=S3DatasetSettings(path=path, content=content, update_strategy=update_strategy),
        linked_service=make_linked_service(),
    )


def test_create_noops_for_none_input_without_contacting_backend():
    dataset = make_dataset(path="not-a-valid-s3-path")

    dataset.create()

    assert isinstance(dataset.output, pd.DataFrame)
    assert dataset.output.empty


def test_create_wraps_missing_connection_as_create_error():
    dataset = make_dataset(path="s3://bucket/file.csv")
    dataset.input = pd.DataFrame({"id": [1]})

    with pytest.raises(CreateError, match="Unable to acquire S3 client"):
        dataset.create()


def test_create_uses_input_copy_as_output_for_s3_writes():
    client = FakeS3Client()
    dataset = make_dataset(path="s3://bucket/file.csv")
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.input = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})

    dataset.create()

    pd.testing.assert_frame_equal(dataset.output, dataset.input)
    assert dataset.output is not dataset.input
    assert len(client.put_calls) == 1
    assert client.put_calls[0]["Bucket"] == "bucket"
    assert client.put_calls[0]["Key"] == "file.csv"


def test_create_with_content_only_keeps_output_as_empty_dataframe():
    client = FakeS3Client()
    dataset = make_dataset(path="s3://bucket/file.csv", content=io.BytesIO(b"hello,s3\n"))
    dataset.linked_service._connection = FakeSession(client=client)

    dataset.create()

    assert isinstance(dataset.output, pd.DataFrame)
    assert dataset.output.empty
    assert client.put_calls[0]["Body"] == b"hello,s3\n"


def test_list_wraps_missing_connection_as_list_error():
    dataset = make_dataset(path="s3://bucket")

    with pytest.raises(ListError, match="Unable to acquire S3 client"):
        dataset.list()


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
    dataset = make_dataset(path="s3://bucket/reports/*.csv")
    dataset.linked_service._connection = FakeSession(client=client)

    dataset.read()

    assert list(dataset.output["id"]) == [1, 2]
    assert list(dataset.output["name"]) == ["Alice", "Bob"]


def test_read_wildcard_with_no_matches_raises_read_error():
    pages = [{"Contents": [{"Key": "reports/readme.txt"}]}]
    bodies = {"reports/readme.txt": b"ignored"}
    client = FakeS3Client(pages=pages, bodies=bodies)
    dataset = make_dataset(path="s3://bucket/reports/*.csv")
    dataset.linked_service._connection = FakeSession(client=client)

    with pytest.raises(ReadError, match="No objects matched wildcard S3 pattern"):
        dataset.read()


def test_read_prefix_with_no_matches_raises_read_error():
    pages = [{"Contents": []}]
    client = FakeS3Client(pages=pages, bodies={})
    dataset = make_dataset(path="s3://bucket/reports")
    dataset.linked_service._connection = FakeSession(client=client)

    with pytest.raises(ReadError, match="No objects found matching S3 prefix"):
        dataset.read()


# ---------------------------------------------------------------------------
# update() - OVERWRITE strategy (default)
# ---------------------------------------------------------------------------


def test_update_overwrite_replaces_existing_object():
    client = FakeS3Client(object_exists=True)
    dataset = make_dataset(path="s3://bucket/file.csv", update_strategy=S3UpdateStrategy.OVERWRITE)
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.input = pd.DataFrame({"id": [99], "name": ["Updated"]})

    dataset.update()

    assert len(client.put_calls) == 1
    assert client.put_calls[0]["Bucket"] == "bucket"
    assert client.put_calls[0]["Key"] == "file.csv"
    assert list(dataset.output.columns) == ["ETag"]
    assert dataset.output.iloc[0]["ETag"] == '"etag"'


def test_update_overwrite_noops_for_empty_input():
    dataset = make_dataset(path="s3://bucket/file.csv", update_strategy=S3UpdateStrategy.OVERWRITE)
    # no linked service set up on purpose — should never contact backend

    dataset.update()

    assert isinstance(dataset.output, pd.DataFrame)
    assert dataset.output.empty


def test_update_overwrite_raises_update_error_when_object_missing():
    client = FakeS3Client(object_exists=False)
    dataset = make_dataset(path="s3://bucket/file.csv", update_strategy=S3UpdateStrategy.OVERWRITE)
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.input = pd.DataFrame({"id": [1]})

    with pytest.raises(UpdateError, match="Target object does not exist"):
        dataset.update()


def test_update_overwrite_with_content_replaces_existing_object():
    client = FakeS3Client(object_exists=True)
    payload = b"id,name\n10,FromContent\n"
    dataset = make_dataset(
        path="s3://bucket/file.csv",
        content=io.BytesIO(payload),
        update_strategy=S3UpdateStrategy.OVERWRITE,
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
    dataset = make_dataset(path="s3://bucket/file.csv", update_strategy=S3UpdateStrategy.APPEND)
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
        path="s3://bucket/file.csv",
        content=io.BytesIO(b"id,name\n2,Bob\n"),
        update_strategy=S3UpdateStrategy.APPEND,
    )
    dataset.linked_service._connection = FakeSession(client=client)

    with pytest.raises(UpdateError, match=r"settings\.content is supported only for OVERWRITE"):
        dataset.update()


def test_update_append_raises_update_error_when_deserializer_missing():
    client = FakeS3Client(object_exists=True, bodies={"file.csv": b"id\n1\n"})
    dataset = make_dataset(path="s3://bucket/file.csv", update_strategy=S3UpdateStrategy.APPEND)
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.deserializer = None
    dataset.input = pd.DataFrame({"id": [2]})

    with pytest.raises(UpdateError, match="Deserializer is not initialized"):
        dataset.update()


def test_update_append_raises_update_error_when_serializer_missing():
    client = FakeS3Client(object_exists=True, bodies={"file.csv": b"id\n1\n"})
    dataset = make_dataset(path="s3://bucket/file.csv", update_strategy=S3UpdateStrategy.APPEND)
    dataset.linked_service._connection = FakeSession(client=client)
    dataset.serializer = None
    dataset.input = pd.DataFrame({"id": [2]})

    with pytest.raises(UpdateError, match="Serializer is not initialized"):
        dataset.update()


def test_update_strategy_enum_values():
    assert S3UpdateStrategy.OVERWRITE == "overwrite"
    assert S3UpdateStrategy.APPEND == "append"


def test_update_default_strategy_is_overwrite():
    settings = S3DatasetSettings(path="s3://bucket/file.csv")
    assert settings.update_strategy is S3UpdateStrategy.OVERWRITE
