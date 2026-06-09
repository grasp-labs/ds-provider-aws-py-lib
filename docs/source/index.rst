Welcome to ds-provider-aws-py-lib's documentation!
=============================================

This library provides AWS linked services for the DS resource plugin framework
(``ds-resource-plugin-py-lib``).

.. toctree::
   :maxdepth: 2
   :caption: Contents:


Linked Services
---------------

AWSLinkedService
~~~~~~~~~~~~~~~~

Generic AWS linked service using static long-term credentials
(``access_key_id`` + ``access_key_secret``). Returns a ``boto3.Session``.

Settings: ``account_id``, ``access_key_id``, ``access_key_secret``, ``region``.

Tenant Partition Linked Services
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Two linked services for per-tenant S3 partition access, backed by
**STS role assumption** (no static credentials required — uses the ambient
execution role / instance profile).

+-----------------------------------------------+---------------------------------------------+
| Type string                                   | IAM role assumed                            |
+===============================================+=============================================+
| ``ds.resource.linked-service.tenant-          | ``ds-<tenant_id>-<building_mode>-reader``   |
| partition-reader``                            |                                             |
+-----------------------------------------------+---------------------------------------------+
| ``ds.resource.linked-service.tenant-          | ``ds-<tenant_id>-<building_mode>-admin``    |
| partition-admin``                             |                                             |
+-----------------------------------------------+---------------------------------------------+

Settings: ``tenant_id`` (UUID), ``building_mode`` (``dev`` / ``prod`` / ``sandbox``),
``region`` (default ``eu-north-1``).

Usage::

    from ds_provider_aws_py_lib.linked_service import (
        TenantPartitionReaderLinkedService,
        TenantPartitionSettings,
    )
    import uuid

    svc = TenantPartitionReaderLinkedService(
        id=uuid.uuid4(),
        name="my-reader",
        version="1.0.0",
        settings=TenantPartitionSettings(
            tenant_id=uuid.UUID("<tenant-uuid>"),
            building_mode="dev",
        ),
    )
    with svc:
        svc.connect()          # assumes the reader IAM role via STS
        s3 = svc.connection.client("s3")

Or via ``ResourceClient`` using the config dict stored in the Config API::

    from ds_resource_plugin_py_lib.common.resource.client import ResourceClient

    client = ResourceClient.get_instance()
    svc = client.linked_service(config_dict)   # config_dict from Config API
    with svc:
        svc.connect()
        s3 = svc.connection.client("s3")

The reader/admin roles and their config dicts are provisioned automatically by
``ds-data-partition-provision`` on every tenant create/update event.


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
