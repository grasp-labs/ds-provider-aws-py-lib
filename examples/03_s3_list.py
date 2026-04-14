from uuid import UUID

from ds_provider_aws_py_lib.dataset import S3Dataset, S3DatasetSettings
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
        settings=S3DatasetSettings(bucket="test-package", key="*/*.csv"),
        linked_service=linked_service,
    )
    linked_service.connect()
    dataset.list()
    print(dataset.output)


if __name__ == "__main__":
    main()
