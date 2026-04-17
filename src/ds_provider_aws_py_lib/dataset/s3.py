import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from fnmatch import fnmatchcase
from typing import Any, Generic, NoReturn, Protocol, TypeAlias, TypeVar, cast

import pandas as pd
from botocore.exceptions import ClientError
from ds_common_logger_py_lib import Logger
from ds_resource_plugin_py_lib.common.resource.dataset import (
    DatasetSettings,
    DatasetStorageFormatType,
    TabularDataset,
)
from ds_resource_plugin_py_lib.common.resource.dataset.errors import (
    CreateError,
    ListError,
    PurgeError,
    ReadError,
    RenameError,
    UpdateError,
)
from ds_resource_plugin_py_lib.common.resource.errors import NotSupportedError
from ds_resource_plugin_py_lib.common.serde.deserialize import PandasDeserializer
from ds_resource_plugin_py_lib.common.serde.serialize import PandasSerializer

from ds_provider_aws_py_lib.enums import ResourceType
from ds_provider_aws_py_lib.linked_service import AWSLinkedService

logger = Logger.get_logger(__name__, package=True)

DatasetMethodError: TypeAlias = (
    type[ReadError] | type[ListError] | type[CreateError] | type[PurgeError] | type[UpdateError] | type[RenameError]
)


class S3UpdateStrategy(StrEnum):
    """Strategy that controls how update() modifies an existing S3 object.

    Attributes:
        OVERWRITE: Replace the entire object with the new payload.
                   The target object must already exist.
        APPEND:    Download the existing object, deserialize it, concatenate
                   new rows from ``self.input``, re-serialize and upload.
                   Requires both serializer and deserializer to be configured.
    """

    OVERWRITE = "overwrite"
    APPEND = "append"


class S3ObjectBody(Protocol):
    def read(self, amt: int | None = None) -> bytes | bytearray: ...


class S3Paginator(Protocol):
    def paginate(self, **kwargs: object) -> Iterable[dict[str, Any]]: ...


class S3ClientProtocol(Protocol):
    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> dict[str, Any]: ...

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...

    def head_bucket(self, *, Bucket: str) -> dict[str, Any]: ...

    def create_bucket(self, *, Bucket: str) -> dict[str, Any]: ...

    def get_paginator(self, operation_name: str) -> S3Paginator: ...

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]: ...

    def delete_bucket(self, *, Bucket: str) -> dict[str, Any]: ...

    def copy_object(self, *, Bucket: str, Key: str, CopySource: dict[str, str]) -> dict[str, Any]: ...

    def delete_object(self, *, Bucket: str, Key: str) -> dict[str, Any]: ...


@dataclass(kw_only=True)
class CreateSettings:
    create_bucket: bool = False
    content: io.BytesIO | None = None


@dataclass(kw_only=True)
class UpdateSettings:
    content: io.BytesIO | None = None
    strategy: str = "overwrite"


@dataclass(kw_only=True)
class RenameSettings:
    new_file_path: str | None = None


@dataclass(kw_only=True)
class PurgeSettings:
    remove_bucket: bool = False


@dataclass(kw_only=True)
class ListSettings:
    download_file: bool = True


@dataclass(kw_only=True)
class S3DatasetSettings(DatasetSettings):
    """Settings for S3 dataset operations.

    Attributes:
        bucket: S3 bucket name.
        key: S3 object key or prefix within ``bucket``.
            Supports glob wildcards (``*``, ``?``, ``[...]``) for read and list.
        create: Settings used by create().
        update: Settings used by update().
        rename: Settings used by rename().
        purge: Settings used by purge().
        list: Settings used by list().
    """

    bucket: str | None = None
    key: str | None = None
    create: CreateSettings = field(default_factory=CreateSettings)
    update: UpdateSettings = field(default_factory=UpdateSettings)
    rename: RenameSettings = field(default_factory=RenameSettings)
    purge: PurgeSettings = field(default_factory=PurgeSettings)
    list: ListSettings = field(default_factory=ListSettings)


S3DatasetSettingsType = TypeVar(
    "S3DatasetSettingsType",
    bound=S3DatasetSettings,
)
AWSLinkedServiceType = TypeVar(
    "AWSLinkedServiceType",
    bound=AWSLinkedService[Any],
)


@dataclass(kw_only=True)
class S3Dataset(
    TabularDataset[
        AWSLinkedServiceType,
        S3DatasetSettingsType,
        PandasSerializer,
        PandasDeserializer,
    ],
    Generic[AWSLinkedServiceType, S3DatasetSettingsType],
):
    linked_service: AWSLinkedServiceType
    settings: S3DatasetSettingsType

    serializer: PandasSerializer | None = field(
        default_factory=lambda: PandasSerializer(format=DatasetStorageFormatType.CSV),
    )
    deserializer: PandasDeserializer | None = field(
        default_factory=lambda: PandasDeserializer(format=DatasetStorageFormatType.CSV),
    )

    @property
    def type(self) -> ResourceType:
        """Resource type for this dataset."""
        return ResourceType.S3_DATASET

    def create(self) -> None:
        """Create/write the current input DataFrame to the configured S3 object."""
        logger.debug(
            "Starting create operation for %s ;account: %s",
            self._current_s3_uri(),
            self.linked_service.settings.account_id,
        )

        if self._should_skip_create():
            self.output = self._build_create_output()
            return

        bucket, key = self._resolve_bucket_key(CreateError)

        self._validate_create_sources(bucket, key)
        self._ensure_bucket_exists(bucket)
        self._ensure_directory_exists(bucket, key)
        self._ensure_object_does_not_exist(bucket, key)

        body = self._build_create_body(bucket, key)
        response = self._upload_create_body(bucket, key, body)
        self.output = self._build_response_output(response)

    def _should_skip_create(self) -> bool:
        """Return True when create() has nothing to do under the contract."""
        input_df = self._get_input_dataframe()
        return self._get_create_content() is None and (input_df is None or input_df.empty)

    def _get_input_dataframe(self) -> pd.DataFrame | None:
        """Return input narrowed to DataFrame | None for create-flow checks."""
        return cast("pd.DataFrame | None", self.input)

    def _build_create_output(self) -> pd.DataFrame:
        """Return contract-aligned create output without mutating self.input."""
        input_df = self._get_input_dataframe()
        if input_df is None:
            return pd.DataFrame()
        return input_df.copy()

    def _validate_create_sources(self, bucket: str, key: str) -> None:
        """Validate mutually exclusive create sources: content vs input."""
        input_df = self._get_input_dataframe()
        has_input_payload = input_df is not None and not input_df.empty
        if self._get_create_content() is not None and has_input_payload:
            raise CreateError(
                message="Both settings.create.content and input are provided. Provide only one source.",
                details={"bucket": bucket, "key": key},
            )

    def _build_create_body(self, bucket: str, key: str) -> bytes:
        """Build upload body from settings.create.content or serialized input."""
        create_content = self._get_create_content()
        if create_content is not None:
            return create_content.getvalue()

        if self.serializer is None:
            raise CreateError(
                message="Serializer is not initialized.",
                status_code=400,
                details={"path": self._current_s3_uri()},
            )

        input_df = self._get_input_dataframe()
        if input_df is None:
            raise CreateError(
                message="Input is None. Provide input DataFrame or settings.create.content.",
                status_code=400,
                details={"bucket": bucket, "key": key},
            )

        try:
            serialized = self.serializer(input_df)
        except Exception as exc:
            raise CreateError(
                message="Failed to serialize input for S3 upload.",
                details={"bucket": bucket, "key": key},
            ) from exc

        if isinstance(serialized, str):
            return serialized.encode("utf-8")
        if isinstance(serialized, (bytes, bytearray)):
            return bytes(serialized)

        raise CreateError(
            message="Unsupported serialized payload type for S3 upload.",
            details={"type": type(serialized).__name__, "bucket": bucket, "key": key},
        )

    def _upload_create_body(self, bucket: str, key: str, body: bytes) -> dict[str, Any]:
        """Upload bytes to S3 and return the backend response payload."""
        s3_client = self._get_s3_client(CreateError)
        try:
            return s3_client.put_object(Bucket=bucket, Key=key, Body=body)
        except ClientError as exc:
            logger.error("Failed to upload object s3://%s/%s: %s", bucket, key, exc)
            raise CreateError(
                message="Failed to upload object to S3.",
                details={"bucket": bucket, "key": key},
            ) from exc

    def _ensure_object_does_not_exist(self, bucket: str, key: str) -> None:
        """Enforce additive-only create by rejecting overwrite of existing object."""
        s3_client = self._get_s3_client(CreateError)
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            raise CreateError(
                message="Target object already exists. create() must not overwrite existing data.",
                status_code=409,
                details={"bucket": bucket, "key": key},
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            not_found = status_code == 404 or error_code in ("404", "NotFound", "NoSuchKey")
            if not not_found:
                raise CreateError(
                    message="Unable to validate target object existence.",
                    details={"bucket": bucket, "key": key, "error_code": error_code},
                ) from exc

    def _ensure_bucket_exists(self, bucket: str) -> None:
        """Ensure bucket exists. Create it only if settings.create_bucket is enabled."""
        s3_client = self._get_s3_client(CreateError)

        try:
            s3_client.head_bucket(Bucket=bucket)
            return
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            missing_bucket = status_code == 404 or error_code in ("404", "NoSuchBucket", "NotFound")
            if not missing_bucket:
                raise CreateError(
                    message="Unable to validate S3 bucket.",
                    details={"bucket": bucket, "error_code": error_code},
                ) from exc

            if not self.settings.create.create_bucket:
                raise CreateError(
                    message="S3 bucket does not exist. Set settings.create_bucket=True to create it.",
                    details={"bucket": bucket},
                ) from exc

            try:
                s3_client.create_bucket(Bucket=bucket)
            except ClientError as create_exc:
                logger.error("Failed to create S3 bucket %s: %s", bucket, create_exc)
                raise CreateError(
                    message="Failed to create S3 bucket.",
                    details={"bucket": bucket},
                ) from create_exc

    def _ensure_directory_exists(self, bucket: str, key: str) -> None:
        """Ensure the key prefix exists by creating a directory marker object when needed."""
        s3_client = self._get_s3_client(CreateError)

        if "/" not in key:
            return

        directory = key.rsplit("/", 1)[0].strip("/")
        if not directory:
            return

        directory_key = f"{directory}/"
        try:
            s3_client.put_object(Bucket=bucket, Key=directory_key, Body=b"")
        except ClientError:
            # Directory markers are optional in S3; upload can still succeed without them.
            return

    def read(self) -> None:
        """Read S3 object(s) into self.output.

        If ``settings.key`` points to a single object the file is read and
        deserialized. If it points to a prefix (directory) all files under that
        prefix are read and concatenated into a single DataFrame.

        Only `ReadError` is raised on failure.
        """
        logger.debug(
            "Starting read operation for %s ;account: %s",
            self._current_s3_uri(),
            self.linked_service.settings.account_id,
        )
        deserializer = self.check_deserializer_exist()

        # Resolve the configured S3 location and obtain the S3 client/session.
        bucket, key = self._resolve_bucket_key(ReadError)
        s3_client = self._get_s3_client()

        if self._contains_wildcard(key):
            self.output = self._read_wildcard(s3_client, bucket, key, deserializer)
            return

        # Decide whether the key is a single object or a prefix
        if self._is_object(s3_client, bucket, key):
            data = self._read_object(s3_client, bucket, key)
            self.output = deserializer(data)
        else:
            # treat as prefix (directory) - ensure prefix ends with '/'
            self.output = self._read_prefix(s3_client, bucket, key)

    @staticmethod
    def _contains_wildcard(value: str) -> bool:
        return any(token in value for token in ("*", "?", "["))

    @staticmethod
    def _wildcard_list_prefix(pattern: str) -> str:
        wildcard_positions = [idx for token in ("*", "?", "[") if (idx := pattern.find(token)) != -1]
        if not wildcard_positions:
            return pattern
        prefix = pattern[: min(wildcard_positions)]
        if "/" in prefix:
            return f"{prefix.rsplit('/', 1)[0]}/"
        return ""

    def _list_matching_keys(self, s3_client: S3ClientProtocol, bucket: str, pattern: str) -> list[str]:
        prefix = self._wildcard_list_prefix(pattern)
        matches: list[str] = []
        try:
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []) or []:
                    obj_key = obj.get("Key")
                    if not obj_key or obj_key.endswith("/"):
                        continue
                    if fnmatchcase(obj_key, pattern):
                        matches.append(obj_key)
        except ClientError as exc:
            logger.error("Failed to list objects for wildcard pattern s3://%s/%s: %s", bucket, pattern, exc)
            raise ReadError(
                message="Failed to list objects for wildcard S3 pattern",
                details={"bucket": bucket, "pattern": pattern},
            ) from exc

        return sorted(matches)

    def _read_wildcard(
        self,
        s3_client: S3ClientProtocol,
        bucket: str,
        pattern: str,
        deserializer: PandasDeserializer,
    ) -> pd.DataFrame:
        keys = self._list_matching_keys(s3_client, bucket, pattern)
        if not keys:
            raise ReadError(
                message="No objects matched wildcard S3 pattern.",
                details={"bucket": bucket, "pattern": pattern},
            )

        dfs: list[pd.DataFrame] = []
        for obj_key in keys:
            data = self._read_object(s3_client, bucket, obj_key)
            try:
                dfs.append(deserializer(data))
            except Exception as exc:
                logger.error("Failed to deserialize S3 object s3://%s/%s: %s", bucket, obj_key, exc)
                raise ReadError(
                    message="Failed to deserialize S3 object in wildcard read",
                    details={"bucket": bucket, "key": obj_key, "pattern": pattern},
                ) from exc

        try:
            return pd.concat(dfs, ignore_index=True)
        except Exception as exc:
            logger.error("Failed to concatenate wildcard read dataframes for s3://%s/%s: %s", bucket, pattern, exc)
            raise ReadError(
                message="Failed to concatenate dataframes from wildcard S3 pattern",
                details={"bucket": bucket, "pattern": pattern},
            ) from exc

    def check_deserializer_exist(self) -> PandasDeserializer:
        deserializer = self.deserializer
        if deserializer is None:
            raise ReadError(
                "Deserializer is not initialized.",
                status_code=400,
                details={"path": self._current_s3_uri()},
            )
        return deserializer

    def _resolve_bucket_key(
        self,
        error_cls: DatasetMethodError = ReadError,
        *,
        allow_bucket_only: bool = False,
    ) -> tuple[str, str]:
        """Resolve bucket/key from explicit settings fields."""
        bucket = self.settings.bucket
        if not bucket:
            raise error_cls(message="S3 bucket must be provided in settings")

        key = self.settings.key or ""
        if not allow_bucket_only and not key:
            raise error_cls(message="S3 key must be provided in settings")

        return bucket, key

    def _current_s3_uri(self, *, allow_bucket_only: bool = False) -> str | None:
        """Return the configured S3 URI when enough settings are present."""
        bucket = self.settings.bucket
        if not bucket:
            return None

        key = self.settings.key or ""
        if not key and not allow_bucket_only:
            return None
        if not key:
            return f"s3://{bucket}"
        return f"s3://{bucket}/{key}"

    def _get_s3_client(self, error_cls: DatasetMethodError = ReadError) -> S3ClientProtocol:
        """Return an S3 client from the linked service boto3 session."""
        try:
            connection = cast("Any", self.linked_service.connection)
            return cast("S3ClientProtocol", connection.client("s3"))
        except Exception as exc:
            logger.error("Unable to acquire S3 client: %s", exc)
            raise error_cls(message="Unable to acquire S3 client", details={}) from exc

    def _is_object(self, s3_client: S3ClientProtocol, bucket: str, key: str) -> bool:
        """Return True when the given key exists as an S3 object."""
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status_code == 404 or error_code in ("404", "NotFound", "NoSuchKey"):
                return False
            logger.error("Error during head_object for s3://%s/%s: %s", bucket, key, exc)
            raise ReadError(
                message="Failed to check S3 object existence",
                details={"bucket": bucket, "key": key},
            ) from exc

    def _read_prefix(self, s3_client: S3ClientProtocol, bucket: str, prefix: str) -> pd.DataFrame:
        """Read all files under a prefix and concatenate them into one DataFrame."""
        deserializer = self.check_deserializer_exist()
        dfs: list[pd.DataFrame] = []
        try:
            paginator = s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix if prefix.endswith("/") else f"{prefix}/"):
                for obj in page.get("Contents", []) or []:
                    obj_key = obj.get("Key")
                    if not obj_key or obj_key.endswith("/"):
                        continue
                    data = self._read_object(s3_client, bucket, obj_key)
                    try:
                        df = deserializer(data)
                    except Exception as exc:
                        logger.error("Failed to deserialize S3 object s3://%s/%s: %s", bucket, obj_key, exc)
                        raise ReadError(
                            message="Failed to deserialize S3 object in prefix",
                            details={"bucket": bucket, "key": obj_key},
                        ) from exc
                    dfs.append(df)
        except ClientError as exc:
            logger.error("Failed to list objects in s3://%s/%s: %s", bucket, prefix, exc)
            raise ReadError(
                message="Failed to list objects in S3 prefix",
                details={"bucket": bucket, "prefix": prefix},
            ) from exc

        if not dfs:
            raise ReadError(
                message="No objects found matching S3 prefix.",
                details={"bucket": bucket, "prefix": prefix},
            )

        try:
            return pd.concat(dfs, ignore_index=True)
        except Exception as exc:
            logger.error("Failed to concat dataframes from prefix s3://%s/%s: %s", bucket, prefix, exc)
            raise ReadError(
                message="Failed to concatenate dataframes from S3 prefix",
                details={"bucket": bucket, "prefix": prefix},
            ) from exc

    @staticmethod
    def _read_object(s3_client: S3ClientProtocol, bucket: str, key: str) -> bytes:
        """Download object bytes from S3."""
        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            body = cast("S3ObjectBody | None", response.get("Body"))
            if body is None:
                raise ReadError(message="S3 object has no body", details={"bucket": bucket, "key": key})
            payload = body.read()
            if isinstance(payload, (bytes, bytearray)):
                return bytes(payload)
            raise ReadError(
                message="S3 object body returned unsupported payload type.",
                details={"bucket": bucket, "key": key, "type": type(payload).__name__},
            )
        except ClientError as exc:
            logger.error("Failed to read s3://%s/%s: %s", bucket, key, exc)
            raise ReadError(message="Failed to read object from S3", details={"bucket": bucket, "key": key}) from exc

    def delete(self) -> NoReturn:
        raise NotSupportedError

    def update(self) -> None:
        """Update an existing S3 object.

        Behaviour is controlled by ``settings.update.strategy``:

        - ``OVERWRITE`` (default): replace the entire object with the new payload.
          The target object must already exist.
        - ``APPEND``: download the current object, deserialize it, concatenate the
          new input rows, re-serialize and upload. Both serializer and deserializer
          must be configured.

        Accepts either ``self.input`` (DataFrame) or ``settings.update.content`` (BytesIO),
        never both. ``settings.update.content`` is supported only for ``OVERWRITE``.
        On success, ``self.output`` contains a one-row DataFrame built from the
        S3 ``put_object`` response payload. When both are empty/None the method
        returns without error (no-op).
        """
        logger.debug(
            "Starting update operation for %s ;account: %s (strategy: %s)",
            self._current_s3_uri(),
            self.linked_service.settings.account_id,
            self._get_update_strategy(),
        )

        if self._should_skip_update():
            self.output = self._build_update_output()
            return

        bucket, key = self._resolve_bucket_key(UpdateError)
        self._validate_update_sources(bucket, key)
        self._ensure_object_exists(bucket, key)

        strategy = self._get_update_strategy()
        if strategy == S3UpdateStrategy.OVERWRITE:
            body = self._build_update_body(bucket, key)
            response = self._upload_update_body(bucket, key, body)
        elif strategy == S3UpdateStrategy.APPEND:
            body = self._build_append_body(bucket, key)
            response = self._upload_update_body(bucket, key, body)
        else:
            raise UpdateError(
                message=f"Unknown update strategy: {strategy!r}",
                details={"bucket": bucket, "key": key, "strategy": str(strategy)},
            )

        self.output = self._build_response_output(response)

    def _should_skip_update(self) -> bool:
        """Return True when update() has nothing to do under the contract."""
        input_df = self._get_input_dataframe()
        return self._get_update_content() is None and (input_df is None or input_df.empty)

    def _build_update_output(self) -> pd.DataFrame:
        """Return contract-aligned update output without mutating self.input."""
        input_df = self._get_input_dataframe()
        if input_df is None:
            return pd.DataFrame()
        return input_df.copy()

    @staticmethod
    def _build_response_output(payload: dict[str, Any]) -> pd.DataFrame:
        """Return a one-row DataFrame from backend response payload."""
        return pd.DataFrame([payload])

    def _validate_update_sources(self, bucket: str, key: str) -> None:
        """Validate mutually exclusive update sources: content vs input."""
        input_df = self._get_input_dataframe()
        has_input_payload = input_df is not None and not input_df.empty
        update_content = self._get_update_content()
        update_strategy = self._get_update_strategy()

        if update_content is not None and has_input_payload:
            raise UpdateError(
                message="Both settings.update.content and input are provided. Provide only one source.",
                details={"bucket": bucket, "key": key},
            )
        if update_content is not None and update_strategy != S3UpdateStrategy.OVERWRITE:
            raise UpdateError(
                message="settings.update.content is supported only for OVERWRITE update strategy.",
                details={"bucket": bucket, "key": key, "strategy": str(update_strategy)},
            )

    def _ensure_object_exists(self, bucket: str, key: str) -> None:
        """Assert the target S3 object exists; raise UpdateError if it does not."""
        s3_client = self._get_s3_client(UpdateError)
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            not_found = status_code == 404 or error_code in ("404", "NotFound", "NoSuchKey")
            if not_found:
                raise UpdateError(
                    message="Target object does not exist. update() requires an existing S3 object.",
                    status_code=404,
                    details={"bucket": bucket, "key": key},
                ) from exc
            raise UpdateError(
                message="Unable to validate target object existence.",
                details={"bucket": bucket, "key": key, "error_code": error_code},
            ) from exc

    def _build_update_body(self, bucket: str, key: str) -> bytes:
        """Build upload body from settings.update.content or serialized input (OVERWRITE strategy)."""
        update_content = self._get_update_content()
        if update_content is not None:
            return update_content.getvalue()

        if self.serializer is None:
            raise UpdateError(
                message="Serializer is not initialized.",
                status_code=400,
                details={"path": self._current_s3_uri()},
            )

        input_df = self._get_input_dataframe()
        if input_df is None:
            raise UpdateError(
                message="Input is None. Provide input DataFrame or settings.update.content.",
                status_code=400,
                details={"bucket": bucket, "key": key},
            )

        try:
            serialized = self.serializer(input_df)
        except Exception as exc:
            raise UpdateError(
                message="Failed to serialize input for S3 upload.",
                details={"bucket": bucket, "key": key},
            ) from exc

        if isinstance(serialized, str):
            return serialized.encode("utf-8")
        if isinstance(serialized, (bytes, bytearray)):
            return bytes(serialized)

        raise UpdateError(
            message="Unsupported serialized payload type for S3 upload.",
            details={"type": type(serialized).__name__, "bucket": bucket, "key": key},
        )

    def _build_append_body(self, bucket: str, key: str) -> bytes:
        """Build upload body for the APPEND strategy.

        Downloads the existing object, deserializes it, concatenates the new
        input rows, then re-serializes the combined result.

        Raises UpdateError if serializer/deserializer are missing or input is absent.
        """
        if self.serializer is None:
            raise UpdateError(
                message="Serializer is not initialized. APPEND strategy requires a serializer.",
                status_code=400,
                details={"path": self._current_s3_uri()},
            )
        if self.deserializer is None:
            raise UpdateError(
                message="Deserializer is not initialized. APPEND strategy requires a deserializer.",
                status_code=400,
                details={"path": self._current_s3_uri()},
            )

        s3_client = self._get_s3_client(UpdateError)

        # Download and deserialize the existing object.
        try:
            existing_bytes = self._read_object(s3_client, bucket, key)
        except ReadError as exc:
            raise UpdateError(
                message="Failed to download existing object for APPEND.",
                details={"bucket": bucket, "key": key},
            ) from exc

        try:
            existing_df = self.deserializer(existing_bytes)
        except Exception as exc:
            raise UpdateError(
                message="Failed to deserialize existing S3 object for APPEND.",
                details={"bucket": bucket, "key": key},
            ) from exc

        input_df = self._get_input_dataframe()
        if input_df is None:
            raise UpdateError(
                message="Input is None. APPEND strategy requires input DataFrame.",
                status_code=400,
                details={"bucket": bucket, "key": key},
            )
        new_df = input_df

        # Concatenate and re-serialize.
        try:
            combined = pd.concat([existing_df, new_df], ignore_index=True)
        except Exception as exc:
            raise UpdateError(
                message="Failed to concatenate existing and new DataFrames for APPEND.",
                details={"bucket": bucket, "key": key},
            ) from exc

        try:
            serialized = self.serializer(combined)
        except Exception as exc:
            raise UpdateError(
                message="Failed to serialize combined DataFrame for APPEND.",
                details={"bucket": bucket, "key": key},
            ) from exc

        if isinstance(serialized, str):
            return serialized.encode("utf-8")
        if isinstance(serialized, (bytes, bytearray)):
            return bytes(serialized)

        raise UpdateError(
            message="Unsupported serialized payload type for S3 APPEND upload.",
            details={"type": type(serialized).__name__, "bucket": bucket, "key": key},
        )

    def _upload_update_body(self, bucket: str, key: str, body: bytes) -> dict[str, Any]:
        """Overwrite the existing S3 object with new bytes and return response payload."""
        s3_client = self._get_s3_client(UpdateError)
        try:
            return s3_client.put_object(Bucket=bucket, Key=key, Body=body)
        except ClientError as exc:
            logger.error("Failed to overwrite object s3://%s/%s: %s", bucket, key, exc)
            raise UpdateError(
                message="Failed to overwrite object in S3.",
                details={"bucket": bucket, "key": key},
            ) from exc

    def purge(self) -> None:
        """Remove a single object, a prefix/directory, or an entire bucket.

        Path behavior:
        - s3://bucket/key -> delete one object when key exists, else treat as prefix
        - s3://bucket/prefix/ -> delete all objects under prefix
        - s3://bucket or bucket -> delete all objects in bucket
        """
        logger.debug(
            "Starting purge operation for %s ;account: %s",
            self._current_s3_uri(allow_bucket_only=True),
            self.linked_service.settings.account_id,
        )

        path = self._current_s3_uri(allow_bucket_only=True)
        bucket, key = self._resolve_bucket_key(PurgeError, allow_bucket_only=True)

        try:
            s3_client = self._get_s3_client()
            delete_responses: list[dict[str, Any]] = []
            delete_bucket_response: dict[str, Any] | None = None
            if not key:
                if not self.settings.purge.remove_bucket:
                    raise PurgeError(
                        message="Bucket purge is disabled. Set settings.remove_bucket=True to allow it.",
                        details={"bucket": bucket, "path": path},
                    )

                keys = self._list_keys_for_prefix(s3_client, bucket, "")
                delete_responses = self._delete_keys(s3_client, bucket, keys)
                try:
                    delete_bucket_response = s3_client.delete_bucket(Bucket=bucket)
                except ClientError as exc:
                    error_code = exc.response.get("Error", {}).get("Code", "")
                    if error_code not in ("NoSuchBucket", "404"):
                        raise
                self.output = self._build_response_output(
                    {
                        "path": path,
                        "bucket": bucket,
                        "purge_scope": "bucket",
                        "delete_responses": delete_responses,
                        "delete_bucket_response": delete_bucket_response,
                    }
                )
                return
            elif self._is_object(s3_client, bucket, key):
                keys = [key]
                purge_scope = "object"
            else:
                prefix = key if key.endswith("/") else f"{key}/"
                keys = self._list_keys_for_prefix(s3_client, bucket, prefix)
                purge_scope = "prefix"

            delete_responses = self._delete_keys(s3_client, bucket, keys)
            self.output = self._build_response_output(
                {
                    "path": path,
                    "bucket": bucket,
                    "purge_scope": purge_scope,
                    "deleted_keys": keys,
                    "delete_responses": delete_responses,
                }
            )
        except PurgeError:
            raise
        except ClientError as exc:
            logger.error("Failed to purge path %s: %s", path, exc)
            raise PurgeError(message=f"Failed to purge S3 path: {exc}", details={"path": path}) from exc
        except Exception as exc:
            logger.error("Unexpected error during purge for %s: %s", path, exc)
            raise PurgeError(message="Unexpected purge failure", details={"path": path}) from exc

    @staticmethod
    def _list_keys_for_prefix(s3_client: S3ClientProtocol, bucket: str, prefix: str) -> list[str]:
        """List all object keys in bucket under prefix.

        Returns an empty list when the bucket does not exist -- a non-existent
        bucket is treated as already empty, consistent with purge() idempotency.
        """
        keys: list[str] = []
        paginator = s3_client.get_paginator("list_objects_v2")
        try:
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []) or []:
                    key = obj.get("Key")
                    if key:
                        keys.append(key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("NoSuchBucket", "404"):
                return []
            raise
        return keys

    @staticmethod
    def _delete_keys(s3_client: S3ClientProtocol, bucket: str, keys: list[str]) -> list[dict[str, Any]]:
        """Delete keys in S3 using batched delete_objects (1000 max per request)."""
        if not keys:
            return []

        responses: list[dict[str, Any]] = []

        for i in range(0, len(keys), 1000):
            batch = keys[i : i + 1000]
            response = s3_client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )
            responses.append(response)
            errors = response.get("Errors", []) or []
            if errors:
                raise PurgeError(
                    message=f"Failed to delete one or more S3 objects: {errors}",
                    details={"bucket": bucket, "errors": errors},
                )

        return responses

    def list(self) -> None:
        """List objects for the configured S3 location and set self.output.

        Output columns depend on ``settings.list.download_file``:
        - True: ``metadata`` and ``content`` (object bytes)
        - False: ``metadata`` only
        """
        logger.debug(
            "Listing objects for %s ;account: %s",
            self._current_s3_uri(allow_bucket_only=True),
            self.linked_service.settings.account_id,
        )

        bucket, prefix = self._resolve_bucket_key(ListError, allow_bucket_only=True)
        download_file = self.settings.list.download_file

        s3_client = self._get_s3_client(ListError)

        rows: list[dict[str, Any]] = []
        try:
            paginator = s3_client.get_paginator("list_objects_v2")
            list_prefix = self._wildcard_list_prefix(prefix) if self._contains_wildcard(prefix) else prefix
            for page in paginator.paginate(Bucket=bucket, Prefix=list_prefix):
                for obj in page.get("Contents", []) or []:
                    obj_key = obj.get("Key")
                    if not obj_key or obj_key.endswith("/"):
                        continue
                    if self._contains_wildcard(prefix) and not fnmatchcase(obj_key, prefix):
                        continue

                    metadata = {
                        "name": obj_key.rsplit("/", 1)[-1],
                        "path": f"s3://{bucket}/{obj_key}",
                        "bucket": bucket,
                        "key": obj_key,
                        "size": obj.get("Size"),
                        "etag": obj.get("ETag"),
                        "last_modified": obj.get("LastModified"),
                        "storage_class": obj.get("StorageClass"),
                    }

                    if download_file:
                        try:
                            content = self._read_object(s3_client, bucket, obj_key)
                        except ReadError as exc:
                            raise ListError(
                                message="Failed to read object content while listing",
                                details={"bucket": bucket, "prefix": prefix, "key": obj_key},
                            ) from exc
                        rows.append({"metadata": metadata, "content": content})
                    else:
                        rows.append({"metadata": metadata})
        except ClientError as exc:
            logger.error("Failed to list objects in s3://%s/%s: %s", bucket, prefix, exc)
            raise ListError(
                message="Failed to list objects in S3",
                details={"bucket": bucket, "prefix": prefix},
            ) from exc

        columns = ["metadata", "content"] if download_file else ["metadata"]
        self.output = pd.DataFrame(rows, columns=columns)

    def rename(self) -> None:
        """Rename an S3 object from ``settings.key`` to ``settings.rename.new_file_path``.

        This operation is implemented as S3 copy-then-delete in the same bucket.
        On success, ``self.output`` is a one-row DataFrame with backend response payload.
        """
        logger.debug(
            "Renaming S3 object from %s to %s ;account: %s",
            self._current_s3_uri(),
            self._rename_target_uri(),
            self.linked_service.settings.account_id,
        )

        source_bucket, source_key = self._resolve_bucket_key(RenameError)
        target_key = self._resolve_rename_target_key()

        if self._contains_wildcard(source_key) or self._contains_wildcard(target_key):
            raise RenameError(message="rename() does not support wildcard paths.")
        if source_key == target_key:
            raise RenameError(message="Source and destination paths must be different for rename().")

        s3_client = self._get_s3_client(RenameError)
        self._ensure_object_exists_for_rename(s3_client, source_bucket, source_key)
        self._ensure_object_absent_for_rename(s3_client, source_bucket, target_key)

        try:
            copy_response = s3_client.copy_object(
                Bucket=source_bucket,
                Key=target_key,
                CopySource={"Bucket": source_bucket, "Key": source_key},
            )
            delete_response = s3_client.delete_object(Bucket=source_bucket, Key=source_key)
            self.output = self._build_response_output(
                {
                    "copy_response": copy_response,
                    "delete_response": delete_response,
                    "source": f"s3://{source_bucket}/{source_key}",
                    "target": f"s3://{source_bucket}/{target_key}",
                }
            )
        except ClientError as exc:
            logger.error(
                "Failed to rename object s3://%s/%s to s3://%s/%s: %s",
                source_bucket,
                source_key,
                source_bucket,
                target_key,
                exc,
            )
            raise RenameError(
                message="Failed to rename S3 object.",
                details={
                    "source": f"s3://{source_bucket}/{source_key}",
                    "target": f"s3://{source_bucket}/{target_key}",
                },
            ) from exc

    def _resolve_rename_target_key(self) -> str:
        new_file_path = self._get_rename_new_file_path()
        if new_file_path:
            return new_file_path

        raise RenameError(message="settings.rename.new_file_path must be provided for rename().")

    def _rename_target_uri(self) -> str | None:
        bucket = self.settings.bucket
        key = self._get_rename_new_file_path()
        if not bucket or not key:
            return None
        return f"s3://{bucket}/{key}"

    @staticmethod
    def _ensure_object_exists_for_rename(s3_client: S3ClientProtocol, bucket: str, key: str) -> None:
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            not_found = status_code == 404 or error_code in ("404", "NotFound", "NoSuchKey")
            if not_found:
                raise RenameError(
                    message="Source object does not exist for rename().",
                    status_code=404,
                    details={"bucket": bucket, "key": key},
                ) from exc
            raise RenameError(
                message="Unable to validate source object for rename().",
                details={"bucket": bucket, "key": key, "error_code": error_code},
            ) from exc

    @staticmethod
    def _ensure_object_absent_for_rename(s3_client: S3ClientProtocol, bucket: str, key: str) -> None:
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
            raise RenameError(
                message="Destination object already exists for rename().",
                status_code=409,
                details={"bucket": bucket, "key": key},
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            not_found = status_code == 404 or error_code in ("404", "NotFound", "NoSuchKey")
            if not not_found:
                raise RenameError(
                    message="Unable to validate destination object for rename().",
                    details={"bucket": bucket, "key": key, "error_code": error_code},
                ) from exc

    def upsert(self) -> NoReturn:
        raise NotSupportedError

    def close(self) -> None:
        self.linked_service.close()

    def _get_create_content(self) -> io.BytesIO | None:
        return self.settings.create.content

    def _get_update_content(self) -> io.BytesIO | None:
        return self.settings.update.content

    def _get_update_strategy(self) -> S3UpdateStrategy:
        return cast("S3UpdateStrategy", self.settings.update.strategy)

    def _get_rename_new_file_path(self) -> str | None:
        return self.settings.rename.new_file_path
