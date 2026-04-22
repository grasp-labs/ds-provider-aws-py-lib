from uuid import UUID

import pandas as pd

from ds_provider_aws_py_lib.dataset import S3Dataset, S3DatasetSettings
from ds_provider_aws_py_lib.dataset.s3 import UpdateSettings
from ds_provider_aws_py_lib.linked_service import AWSLinkedService, AWSLinkedServiceSettings


def main():
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
            key="test3/test9.csv",
            update=UpdateSettings(strategy="append"),
        ),
        linked_service=linked_service,
    )
    linked_service.connect()
    dataset.input = pd.DataFrame(
        {
            "id": [7, 8, 9],
            "name": ["Alice", "Bob", "Charlie"],
            "age": [25, 30, 35],
        }
    )
    dataset.update()
    print(dataset.output)


if __name__ == "__main__":
    main()
