"""KKStorageStack: S3 buckets, S3 Vectors, DynamoDB tables, KMS keys, shared Lambda layer."""
import os
from pathlib import Path

from aws_cdk import (
    BundlingOptions,
    CfnTag,
    Duration,
    RemovalPolicy,
    Stack,
    CfnOutput,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    aws_kms as kms,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_s3vectors as s3vectors,
)
from constructs import Construct


class KKStorageStack(Stack):
    """Storage layer: S3 buckets, S3 Vectors, DynamoDB tables, KMS keys."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env_name = self.node.try_get_context("env") or self.node.try_get_context("default_environment") or "dev"
        environments = self.node.try_get_context("environments") or {}
        env_config = environments.get(env_name, {})
        lifecycle_days = env_config.get("s3_lifecycle_days", 90)

        # --- KMS key for S3 encryption ---
        self.s3_kms_key = kms.Key(
            self,
            "S3KmsKey",
            alias=f"kk-{env_name}-s3",
            description="KMS key for KnowledgeKeeper S3 bucket encryption",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- Raw archives S3 bucket ---
        self.raw_archives_bucket = s3.Bucket(
            self,
            "RawArchivesBucket",
            bucket_name=f"kk-{self.account}-{env_name}-raw-archives",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.s3_kms_key,
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="ExpireRawArchives",
                    expiration=Duration.days(lifecycle_days),
                    enabled=True,
                ),
            ],
        )

        # --- Stack outputs (S3) ---
        CfnOutput(self, "RawArchivesBucketName", value=self.raw_archives_bucket.bucket_name)
        CfnOutput(self, "RawArchivesBucketArn", value=self.raw_archives_bucket.bucket_arn)
        CfnOutput(self, "S3KmsKeyArn", value=self.s3_kms_key.key_arn)

        # --- KMS key for S3 Vectors encryption ---
        self.vectors_kms_key = kms.Key(
            self,
            "VectorsKmsKey",
            alias=f"kk-{env_name}-vectors",
            description="KMS key for KnowledgeKeeper S3 Vectors encryption",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Grant S3 Vectors indexing service principal access to the KMS key
        self.vectors_kms_key.add_to_resource_policy(
            iam.PolicyStatement(
                sid="AllowS3VectorsIndexing",
                actions=[
                    "kms:Decrypt",
                    "kms:GenerateDataKey",
                    "kms:DescribeKey",
                    "kms:CreateGrant",
                ],
                principals=[iam.ServicePrincipal("indexing.s3vectors.amazonaws.com")],
                resources=["*"],
            )
        )

        # --- S3 Vector Bucket ---
        self.vector_bucket = s3vectors.CfnVectorBucket(
            self,
            "VectorBucket",
            vector_bucket_name=f"kk-{env_name}",
            encryption_configuration=s3vectors.CfnVectorBucket.EncryptionConfigurationProperty(
                sse_type="aws:kms",
                kms_key_arn=self.vectors_kms_key.key_arn,
            ),
            tags=[CfnTag(key="Environment", value=env_name)],
        )

        # --- S3 Vector Index ---
        self.vector_index = s3vectors.CfnIndex(
            self,
            "VectorIndex",
            vector_bucket_name=self.vector_bucket.vector_bucket_name,
            index_name=f"kk-{env_name}-chunks",
            dimension=1024,
            distance_metric="cosine",
            data_type="float32",
            metadata_configuration=s3vectors.CfnIndex.MetadataConfigurationProperty(
                non_filterable_metadata_keys=["content", "subject"],
            ),
            encryption_configuration=s3vectors.CfnIndex.EncryptionConfigurationProperty(
                sse_type="aws:kms",
                kms_key_arn=self.vectors_kms_key.key_arn,
            ),
            tags=[CfnTag(key="Environment", value=env_name)],
        )
        self.vector_index.add_dependency(self.vector_bucket)

        # --- Stack outputs (S3 Vectors) ---
        CfnOutput(self, "VectorBucketName", value=f"kk-{env_name}")
        CfnOutput(self, "VectorIndexName", value=f"kk-{env_name}-chunks")
        CfnOutput(self, "VectorsKmsKeyArn", value=self.vectors_kms_key.key_arn)

        # --- KMS key for DynamoDB encryption ---
        self.dynamo_kms_key = kms.Key(
            self,
            "DynamoKmsKey",
            alias=f"kk-{env_name}-dynamo",
            description="KMS key for KnowledgeKeeper DynamoDB encryption",
            enable_key_rotation=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- DynamoDB: KKTwins table ---
        self.twins_table = dynamodb.Table(
            self,
            "TwinsTable",
            table_name=f"KK{env_name.capitalize()}Twins",
            partition_key=dynamodb.Attribute(
                name="employeeId", type=dynamodb.AttributeType.STRING
            ),
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.dynamo_kms_key,
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )
        self.twins_table.add_global_secondary_index(
            index_name="status-offboardDate-index",
            partition_key=dynamodb.Attribute(
                name="status", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="offboardDate", type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL,
        )

        # --- DynamoDB: KKAudit table ---
        audit_ttl_years = env_config.get("audit_ttl_years", 7)
        self.audit_table = dynamodb.Table(
            self,
            "AuditTable",
            table_name=f"KK{env_name.capitalize()}Audit",
            partition_key=dynamodb.Attribute(
                name="requestId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.dynamo_kms_key,
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
        )

        # --- DynamoDB: KKAccess table ---
        self.access_table = dynamodb.Table(
            self,
            "AccessTable",
            table_name=f"KK{env_name.capitalize()}Access",
            partition_key=dynamodb.Attribute(
                name="userId", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="employeeId", type=dynamodb.AttributeType.STRING
            ),
            encryption=dynamodb.TableEncryption.CUSTOMER_MANAGED,
            encryption_key=self.dynamo_kms_key,
            point_in_time_recovery=True,
            removal_policy=RemovalPolicy.RETAIN,
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        )

        # --- Stack outputs (DynamoDB) ---
        CfnOutput(self, "TwinsTableName", value=self.twins_table.table_name)
        CfnOutput(self, "TwinsTableArn", value=self.twins_table.table_arn)
        CfnOutput(self, "AuditTableName", value=self.audit_table.table_name)
        CfnOutput(self, "AuditTableArn", value=self.audit_table.table_arn)
        CfnOutput(self, "AccessTableName", value=self.access_table.table_name)
        CfnOutput(self, "AccessTableArn", value=self.access_table.table_arn)
        CfnOutput(self, "DynamoKmsKeyArn", value=self.dynamo_kms_key.key_arn)

        # --- Shared Lambda Layer ---
        # Resolve path to lambdas/shared/ relative to the infrastructure directory.
        shared_layer_path = str(
            Path(__file__).resolve().parent.parent.parent / "lambdas" / "shared"
        )

        self.shared_layer = _lambda.LayerVersion(
            self,
            "SharedLayer",
            layer_version_name=f"kk-{env_name}-shared",
            description="Shared utilities: models, bedrock, dynamo, s3vectors_client",
            compatible_runtimes=[_lambda.Runtime.PYTHON_3_12],
            code=_lambda.Code.from_asset(
                shared_layer_path,
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install -r requirements.txt -t /asset-output/python"
                        " && mkdir -p /asset-output/python/shared"
                        " && cp *.py /asset-output/python/shared/"
                        " && touch /asset-output/python/shared/__init__.py",
                    ],
                ),
            ),
        )

        # --- Stack outputs (Lambda Layer) ---
        CfnOutput(self, "SharedLayerArn", value=self.shared_layer.layer_version_arn)
