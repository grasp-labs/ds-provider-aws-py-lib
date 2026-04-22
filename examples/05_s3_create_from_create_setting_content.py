import io
from uuid import UUID

import pandas as pd

from ds_provider_aws_py_lib.dataset import S3Dataset, S3DatasetSettings
from ds_provider_aws_py_lib.dataset.s3 import CreateSettings
from ds_provider_aws_py_lib.linked_service import AWSLinkedService, AWSLinkedServiceSettings


def main():
    df = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "name": ["Alice", "Bob", "Charlie"],
            "age": [25, 30, 35],
        }
    )
    dataframe_as_binary: io.BytesIO = io.BytesIO(df.to_csv(index=False).encode("utf-8"))
    linked_service = AWSLinkedService(
        id=UUID("00000000-0000-0000-0000-000000000000"),
        name="test-name",
        version="1.0.0",
        settings=AWSLinkedServiceSettings(
            account_id="...",
            access_key_id="...",
            access_key_secret="...",
            region="us-east-1",
        ),
    )
    dataset = S3Dataset(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        name="test-s3-dataset",
        version="1.0.0",
        settings=S3DatasetSettings(
            bucket="test-package",
            key="test/testbca8.csv",
            create=CreateSettings(content=dataframe_as_binary),
        ),
        linked_service=linked_service,
    )
    linked_service.connect()

    dataset.create()
    print(dataset.output)


if __name__ == "__main__":
    main()
