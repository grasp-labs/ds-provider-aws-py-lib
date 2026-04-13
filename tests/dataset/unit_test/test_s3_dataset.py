from __future__ import annotations

import io
from uuid import UUID

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from ds_resource_plugin_py_lib.common.resource.dataset.errors import CreateError, ListError

from ds_provider_aws_py_lib.dataset import S3Dataset, S3DatasetSettings
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
        raise ClientError(
            {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}},
            "HeadObject",
        )

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


def make_dataset(*, path: str = "s3://bucket/file.csv", content: io.BytesIO | None = None) -> S3Dataset:
    return S3Dataset(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        name="test-s3-dataset",
        version="1.0.0",
        settings=S3DatasetSettings(path=path, content=content),
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
