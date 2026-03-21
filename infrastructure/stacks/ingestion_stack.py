"""KKIngestionStack: SQS queues (with DLQs), Lambda functions, S3 event notifications."""
from pathlib import Path

from aws_cdk import (
    Duration,
    Stack,
    CfnOutput,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_lambda_event_sources as lambda_events,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sqs as sqs,
)
from constructs import Construct


class KKIngestionStack(Stack):
    """Ingestion layer: SQS queues, Lambda functions, S3 event notifications."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        storage_stack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env_name = (
            self.node.try_get_context("env")
            or self.node.try_get_context("default_environment")
            or "dev"
        )

        # --- ParseQueue + DLQ ---
        self.parse_dlq = sqs.Queue(
            self,
            "ParseDLQ",
            queue_name=f"kk-{env_name}-parse-dlq",
            retention_period=Duration.days(14),
        )
        self.parse_queue = sqs.Queue(
            self,
            "ParseQueue",
            queue_name=f"kk-{env_name}-parse",
            visibility_timeout=Duration.seconds(300),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.parse_dlq,
            ),
        )

        # --- CleanQueue + DLQ ---
        self.clean_dlq = sqs.Queue(
            self,
            "CleanDLQ",
            queue_name=f"kk-{env_name}-clean-dlq",
            retention_period=Duration.days(14),
        )
        self.clean_queue = sqs.Queue(
            self,
            "CleanQueue",
            queue_name=f"kk-{env_name}-clean",
            visibility_timeout=Duration.seconds(300),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.clean_dlq,
            ),
        )

        # --- EmbedQueue + DLQ ---
        self.embed_dlq = sqs.Queue(
            self,
            "EmbedDLQ",
            queue_name=f"kk-{env_name}-embed-dlq",
            retention_period=Duration.days(14),
        )
        self.embed_queue = sqs.Queue(
            self,
            "EmbedQueue",
            queue_name=f"kk-{env_name}-embed",
            visibility_timeout=Duration.seconds(600),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.embed_dlq,
            ),
        )

        # --- Lambda: ingest_trigger ---
        trigger_code_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "lambdas"
            / "ingestion"
            / "trigger"
        )

        # Dedicated IAM role (least-privilege)
        trigger_role = iam.Role(
            self,
            "IngestTriggerRole",
            role_name=f"kk-{env_name}-ingestion-trigger",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # SQS:SendMessage on ParseQueue only
        trigger_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[self.parse_queue.queue_arn],
            )
        )

        # DynamoDB:UpdateItem on Twins table only
        trigger_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:UpdateItem"],
                resources=[storage_stack.twins_table.table_arn],
            )
        )

        # S3:GetObject on raw-archives bucket only
        trigger_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[
                    storage_stack.raw_archives_bucket.bucket_arn + "/*"
                ],
            )
        )

        # KMS decrypt for S3 bucket key
        trigger_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=[storage_stack.s3_kms_key.key_arn],
            )
        )

        self.ingest_trigger_fn = _lambda.Function(
            self,
            "IngestTriggerFn",
            function_name=f"kk-{env_name}-ingestion-trigger",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(trigger_code_path),
            role=trigger_role,
            timeout=Duration.seconds(60),
            memory_size=256,
            layers=[storage_stack.shared_layer],
            environment={
                "PARSE_QUEUE_URL": self.parse_queue.queue_url,
                "TWINS_TABLE_NAME": storage_stack.twins_table.table_name,
            },
        )

        # S3 event notification: trigger on .mbox uploads
        storage_stack.raw_archives_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(self.ingest_trigger_fn),
            s3.NotificationKeyFilter(suffix=".mbox"),
        )

        # --- Lambda: parser ---
        parser_code_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "lambdas"
            / "ingestion"
            / "parser"
        )

        # Dedicated IAM role (least-privilege)
        parser_role = iam.Role(
            self,
            "ParserRole",
            role_name=f"kk-{env_name}-ingestion-parser",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # S3:GetObject on raw-archives bucket
        parser_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[
                    storage_stack.raw_archives_bucket.bucket_arn + "/*"
                ],
            )
        )

        # KMS decrypt for S3 bucket key
        parser_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=[storage_stack.s3_kms_key.key_arn],
            )
        )

        # SQS:SendMessage on CleanQueue
        parser_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[self.clean_queue.queue_arn],
            )
        )

        # SQS:ReceiveMessage + DeleteMessage + GetQueueAttributes on ParseQueue
        parser_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:GetQueueAttributes",
                ],
                resources=[self.parse_queue.queue_arn],
            )
        )

        self.parser_fn = _lambda.Function(
            self,
            "ParserFn",
            function_name=f"kk-{env_name}-ingestion-parser",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(parser_code_path),
            role=parser_role,
            timeout=Duration.seconds(300),
            memory_size=512,
            layers=[storage_stack.shared_layer],
            environment={
                "CLEAN_QUEUE_URL": self.clean_queue.queue_url,
                "RAW_ARCHIVES_BUCKET": storage_stack.raw_archives_bucket.bucket_name,
            },
        )

        # SQS event source mapping: ParseQueue → parser (batch size 10)
        self.parser_fn.add_event_source(
            lambda_events.SqsEventSource(
                self.parse_queue,
                batch_size=10,
                report_batch_item_failures=True,
            )
        )

        # --- Lambda: cleaner ---
        cleaner_code_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "lambdas"
            / "ingestion"
            / "cleaner"
        )

        # Dedicated IAM role (least-privilege)
        cleaner_role = iam.Role(
            self,
            "CleanerRole",
            role_name=f"kk-{env_name}-ingestion-cleaner",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # Comprehend:DetectPiiEntities
        cleaner_role.add_to_policy(
            iam.PolicyStatement(
                actions=["comprehend:DetectPiiEntities"],
                resources=["*"],
            )
        )

        # SQS:SendMessage on EmbedQueue
        cleaner_role.add_to_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[self.embed_queue.queue_arn],
            )
        )

        # SQS:ReceiveMessage + DeleteMessage + GetQueueAttributes on CleanQueue
        cleaner_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:GetQueueAttributes",
                ],
                resources=[self.clean_queue.queue_arn],
            )
        )

        self.cleaner_fn = _lambda.Function(
            self,
            "CleanerFn",
            function_name=f"kk-{env_name}-ingestion-cleaner",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(cleaner_code_path),
            role=cleaner_role,
            timeout=Duration.seconds(300),
            memory_size=512,
            layers=[storage_stack.shared_layer],
            environment={
                "EMBED_QUEUE_URL": self.embed_queue.queue_url,
            },
        )

        # SQS event source mapping: CleanQueue → cleaner (batch size 5)
        self.cleaner_fn.add_event_source(
            lambda_events.SqsEventSource(
                self.clean_queue,
                batch_size=5,
                report_batch_item_failures=True,
            )
        )

        # --- Lambda: embedder ---
        embedder_code_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "lambdas"
            / "ingestion"
            / "embedder"
        )

        # Dedicated IAM role (least-privilege)
        embedder_role = iam.Role(
            self,
            "EmbedderRole",
            role_name=f"kk-{env_name}-ingestion-embedder",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # Bedrock:InvokeModel scoped to Nova Embeddings model
        embedder_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/amazon.nova-2-multimodal-embeddings-v1:0"
                ],
            )
        )

        # S3Vectors:PutVectors on the vector bucket
        embedder_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3vectors:PutVectors"],
                resources=[
                    f"arn:aws:s3vectors:{self.region}:{self.account}:vector-bucket/kk-{env_name}/*"
                ],
            )
        )

        # KMS encrypt/decrypt for S3 Vectors
        embedder_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[storage_stack.vectors_kms_key.key_arn],
            )
        )

        # DynamoDB:UpdateItem on Twins table
        embedder_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:UpdateItem"],
                resources=[storage_stack.twins_table.table_arn],
            )
        )

        # KMS decrypt for DynamoDB
        embedder_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[storage_stack.dynamo_kms_key.key_arn],
            )
        )

        # SQS:ReceiveMessage + DeleteMessage + GetQueueAttributes on EmbedQueue
        embedder_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "sqs:ReceiveMessage",
                    "sqs:DeleteMessage",
                    "sqs:GetQueueAttributes",
                ],
                resources=[self.embed_queue.queue_arn],
            )
        )

        self.embedder_fn = _lambda.Function(
            self,
            "EmbedderFn",
            function_name=f"kk-{env_name}-ingestion-embedder",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(embedder_code_path),
            role=embedder_role,
            timeout=Duration.minutes(10),
            memory_size=1024,
            layers=[storage_stack.shared_layer],
            environment={
                "VECTOR_BUCKET_NAME": f"kk-{env_name}",
                "VECTOR_INDEX_NAME": f"kk-{env_name}-chunks",
                "TWINS_TABLE_NAME": storage_stack.twins_table.table_name,
            },
        )

        # SQS event source mapping: EmbedQueue → embedder (batch size 3)
        self.embedder_fn.add_event_source(
            lambda_events.SqsEventSource(
                self.embed_queue,
                batch_size=3,
                report_batch_item_failures=True,
            )
        )

        # --- Lambda: email_fetcher ---
        email_fetcher_code_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "lambdas"
            / "ingestion"
            / "email_fetcher"
        )

        # Dedicated IAM role (least-privilege)
        email_fetcher_role = iam.Role(
            self,
            "EmailFetcherRole",
            role_name=f"kk-{env_name}-ingestion-email-fetcher",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # S3:PutObject on raw-archives bucket
        email_fetcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"],
                resources=[
                    storage_stack.raw_archives_bucket.bucket_arn + "/*"
                ],
            )
        )

        # KMS encrypt for S3 bucket key
        email_fetcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Encrypt", "kms:GenerateDataKey"],
                resources=[storage_stack.s3_kms_key.key_arn],
            )
        )

        # SecretsManager:GetSecretValue for Google Workspace credentials
        email_fetcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:kk/{env_name}/google-workspace-creds*"
                ],
            )
        )

        # DynamoDB:UpdateItem on Twins table (status updates)
        email_fetcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:UpdateItem"],
                resources=[storage_stack.twins_table.table_arn],
            )
        )

        # KMS decrypt for DynamoDB
        email_fetcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[storage_stack.dynamo_kms_key.key_arn],
            )
        )

        self.email_fetcher_fn = _lambda.Function(
            self,
            "EmailFetcherFn",
            function_name=f"kk-{env_name}-ingestion-email-fetcher",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(email_fetcher_code_path),
            role=email_fetcher_role,
            timeout=Duration.minutes(15),
            memory_size=1024,
            layers=[storage_stack.shared_layer],
            environment={
                "RAW_ARCHIVES_BUCKET": storage_stack.raw_archives_bucket.bucket_name,
                "GOOGLE_CREDS_SECRET": f"kk/{env_name}/google-workspace-creds",
                "TWINS_TABLE_NAME": storage_stack.twins_table.table_name,
            },
        )

        # --- Lambda: m365_email_fetcher ---
        m365_email_fetcher_code_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "lambdas"
            / "ingestion"
            / "m365_email_fetcher"
        )

        # Dedicated IAM role (least-privilege)
        m365_email_fetcher_role = iam.Role(
            self,
            "M365EmailFetcherRole",
            role_name=f"kk-{env_name}-ingestion-m365-email-fetcher",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # S3:PutObject on raw-archives bucket
        m365_email_fetcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"],
                resources=[
                    storage_stack.raw_archives_bucket.bucket_arn + "/*"
                ],
            )
        )

        # KMS encrypt for S3 bucket key
        m365_email_fetcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Encrypt", "kms:GenerateDataKey"],
                resources=[storage_stack.s3_kms_key.key_arn],
            )
        )

        # SecretsManager:GetSecretValue for M365 credentials
        m365_email_fetcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:kk/{env_name}/m365-credentials*"
                ],
            )
        )

        # DynamoDB:UpdateItem on Twins table (status updates)
        m365_email_fetcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:UpdateItem"],
                resources=[storage_stack.twins_table.table_arn],
            )
        )

        # KMS decrypt for DynamoDB
        m365_email_fetcher_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[storage_stack.dynamo_kms_key.key_arn],
            )
        )

        self.m365_email_fetcher_fn = _lambda.Function(
            self,
            "M365EmailFetcherFn",
            function_name=f"kk-{env_name}-ingestion-m365-email-fetcher",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(m365_email_fetcher_code_path),
            role=m365_email_fetcher_role,
            timeout=Duration.minutes(15),
            memory_size=1024,
            layers=[storage_stack.shared_layer],
            environment={
                "RAW_ARCHIVES_BUCKET": storage_stack.raw_archives_bucket.bucket_name,
                "M365_CREDS_SECRET": f"kk/{env_name}/m365-credentials",
                "TWINS_TABLE_NAME": storage_stack.twins_table.table_name,
            },
        )

        # --- Stack outputs (SQS) ---
        CfnOutput(self, "ParseQueueUrl", value=self.parse_queue.queue_url)
        CfnOutput(self, "ParseQueueArn", value=self.parse_queue.queue_arn)
        CfnOutput(self, "ParseDLQUrl", value=self.parse_dlq.queue_url)
        CfnOutput(self, "ParseDLQArn", value=self.parse_dlq.queue_arn)

        CfnOutput(self, "CleanQueueUrl", value=self.clean_queue.queue_url)
        CfnOutput(self, "CleanQueueArn", value=self.clean_queue.queue_arn)
        CfnOutput(self, "CleanDLQUrl", value=self.clean_dlq.queue_url)
        CfnOutput(self, "CleanDLQArn", value=self.clean_dlq.queue_arn)

        CfnOutput(self, "EmbedQueueUrl", value=self.embed_queue.queue_url)
        CfnOutput(self, "EmbedQueueArn", value=self.embed_queue.queue_arn)
        CfnOutput(self, "EmbedDLQUrl", value=self.embed_dlq.queue_url)
        CfnOutput(self, "EmbedDLQArn", value=self.embed_dlq.queue_arn)

        # --- Stack outputs (Lambda) ---
        CfnOutput(
            self,
            "IngestTriggerFnArn",
            value=self.ingest_trigger_fn.function_arn,
        )
        CfnOutput(
            self,
            "ParserFnArn",
            value=self.parser_fn.function_arn,
        )
        CfnOutput(
            self,
            "CleanerFnArn",
            value=self.cleaner_fn.function_arn,
        )
        CfnOutput(
            self,
            "EmbedderFnArn",
            value=self.embedder_fn.function_arn,
        )
        CfnOutput(
            self,
            "EmailFetcherFnArn",
            value=self.email_fetcher_fn.function_arn,
        )
        CfnOutput(
            self,
            "M365EmailFetcherFnArn",
            value=self.m365_email_fetcher_fn.function_arn,
        )
