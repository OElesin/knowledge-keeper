"""KKQueryStack: API Gateway REST API with API Key auth, Lambda functions, API routes."""
from pathlib import Path

from aws_cdk import (
    Duration,
    Stack,
    CfnOutput,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_lambda as _lambda,
)
from constructs import Construct


class KKQueryStack(Stack):
    """Query layer: API Gateway REST API, Lambda functions, API routes."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        storage_stack,
        ingestion_stack=None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env_name = (
            self.node.try_get_context("env")
            or self.node.try_get_context("default_environment")
            or "dev"
        )

        self.storage_stack = storage_stack

        # --- REST API ---
        self.api = apigateway.RestApi(
            self,
            "KKApi",
            rest_api_name=f"kk-{env_name}-api",
            description="KnowledgeKeeper REST API",
            deploy_options=apigateway.StageOptions(
                stage_name="prod",
                throttling_rate_limit=500,
                throttling_burst_limit=1000,
            ),
            default_cors_preflight_options=apigateway.CorsOptions(
                allow_origins=apigateway.Cors.ALL_ORIGINS,
                allow_methods=apigateway.Cors.ALL_METHODS,
                allow_headers=[
                    "Content-Type",
                    "Authorization",
                    "x-api-key",
                    "x-user-id",
                ],
            ),
        )

        # --- Usage Plan ---
        self.usage_plan = self.api.add_usage_plan(
            "KKUsagePlan",
            name=f"kk-{env_name}-usage-plan",
            throttle=apigateway.ThrottleSettings(
                rate_limit=500,
                burst_limit=1000,
            ),
        )
        self.usage_plan.add_api_stage(stage=self.api.deployment_stage)

        # --- API Key ---
        self.api_key = apigateway.ApiKey(
            self,
            "KKApiKey",
            api_key_name=f"kk-{env_name}-api-key",
            enabled=True,
        )
        self.usage_plan.add_api_key(self.api_key)

        # =====================================================================
        # Lambda: query_handler
        # =====================================================================
        query_handler_code_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "lambdas"
            / "query"
            / "query_handler"
        )

        # Dedicated IAM role (least-privilege)
        query_handler_role = iam.Role(
            self,
            "QueryHandlerRole",
            role_name=f"kk-{env_name}-query-handler",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # Bedrock:InvokeModel scoped to Nova Embeddings + Nova Pro
        query_handler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/amazon.nova-2-multimodal-embeddings-v1:0",
                    f"arn:aws:bedrock:{self.region}::foundation-model/amazon.nova-pro-v1:0",
                ],
            )
        )

        # S3Vectors:QueryVectors on the vector bucket
        query_handler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3vectors:QueryVectors"],
                resources=[
                    f"arn:aws:s3vectors:{self.region}:{self.account}:vector-bucket/kk-{env_name}/*"
                ],
            )
        )

        # KMS decrypt for S3 Vectors
        query_handler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=[storage_stack.vectors_kms_key.key_arn],
            )
        )

        # DynamoDB:GetItem on Access + Twins tables
        query_handler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem"],
                resources=[
                    storage_stack.access_table.table_arn,
                    storage_stack.twins_table.table_arn,
                ],
            )
        )

        # DynamoDB:PutItem on Audit table
        query_handler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:PutItem"],
                resources=[storage_stack.audit_table.table_arn],
            )
        )

        # KMS encrypt/decrypt for DynamoDB
        query_handler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[storage_stack.dynamo_kms_key.key_arn],
            )
        )

        self.query_handler_fn = _lambda.Function(
            self,
            "QueryHandlerFn",
            function_name=f"kk-{env_name}-query-handler",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(query_handler_code_path),
            role=query_handler_role,
            timeout=Duration.seconds(30),
            memory_size=512,
            layers=[storage_stack.shared_layer],
            environment={
                "VECTOR_BUCKET_NAME": f"kk-{env_name}",
                "VECTOR_INDEX_NAME": f"kk-{env_name}-chunks",
                "TWINS_TABLE_NAME": storage_stack.twins_table.table_name,
                "ACCESS_TABLE_NAME": storage_stack.access_table.table_name,
                "AUDIT_TABLE_NAME": storage_stack.audit_table.table_name,
            },
        )

        # =====================================================================
        # Lambda: admin
        # =====================================================================
        admin_code_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "lambdas"
            / "query"
            / "admin"
        )

        # Dedicated IAM role (least-privilege)
        admin_role = iam.Role(
            self,
            "AdminRole",
            role_name=f"kk-{env_name}-query-admin",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
        )

        # DynamoDB full CRUD on Twins, Access, Audit tables
        admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:GetItem",
                    "dynamodb:PutItem",
                    "dynamodb:UpdateItem",
                    "dynamodb:DeleteItem",
                    "dynamodb:Scan",
                    "dynamodb:Query",
                ],
                resources=[
                    storage_stack.twins_table.table_arn,
                    storage_stack.twins_table.table_arn + "/index/*",
                    storage_stack.access_table.table_arn,
                    storage_stack.audit_table.table_arn,
                ],
            )
        )

        # S3Vectors:DeleteVectors on the vector bucket
        admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3vectors:DeleteVectors"],
                resources=[
                    f"arn:aws:s3vectors:{self.region}:{self.account}:vector-bucket/kk-{env_name}/*"
                ],
            )
        )

        # S3:DeleteObject on raw-archives bucket
        admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:DeleteObject", "s3:ListBucket"],
                resources=[
                    storage_stack.raw_archives_bucket.bucket_arn,
                    storage_stack.raw_archives_bucket.bucket_arn + "/*",
                ],
            )
        )

        # KMS decrypt for S3, S3 Vectors, DynamoDB
        admin_role.add_to_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt", "kms:GenerateDataKey"],
                resources=[
                    storage_stack.s3_kms_key.key_arn,
                    storage_stack.vectors_kms_key.key_arn,
                    storage_stack.dynamo_kms_key.key_arn,
                ],
            )
        )

        # Lambda:InvokeFunction on email_fetcher and m365_email_fetcher (async invocation from admin)
        if ingestion_stack is not None:
            admin_role.add_to_policy(
                iam.PolicyStatement(
                    actions=["lambda:InvokeFunction"],
                    resources=[
                        ingestion_stack.email_fetcher_fn.function_arn,
                        ingestion_stack.m365_email_fetcher_fn.function_arn,
                    ],
                )
            )

        self.admin_fn = _lambda.Function(
            self,
            "AdminFn",
            function_name=f"kk-{env_name}-query-admin",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(admin_code_path),
            role=admin_role,
            timeout=Duration.seconds(30),
            memory_size=512,
            layers=[storage_stack.shared_layer],
            environment={
                "TWINS_TABLE_NAME": storage_stack.twins_table.table_name,
                "ACCESS_TABLE_NAME": storage_stack.access_table.table_name,
                "AUDIT_TABLE_NAME": storage_stack.audit_table.table_name,
                "VECTOR_BUCKET_NAME": f"kk-{env_name}",
                "VECTOR_INDEX_NAME": f"kk-{env_name}-chunks",
                "RAW_ARCHIVES_BUCKET": storage_stack.raw_archives_bucket.bucket_name,
                "EMAIL_FETCHER_FN_NAME": (
                    ingestion_stack.email_fetcher_fn.function_name
                    if ingestion_stack
                    else ""
                ),
                "M365_EMAIL_FETCHER_FN_NAME": (
                    ingestion_stack.m365_email_fetcher_fn.function_name
                    if ingestion_stack
                    else ""
                ),
            },
        )

        # =====================================================================
        # API Gateway — Lambda proxy integrations
        # =====================================================================
        admin_integration = apigateway.LambdaIntegration(self.admin_fn)
        query_integration = apigateway.LambdaIntegration(self.query_handler_fn)

        # =====================================================================
        # API Gateway — Resource tree and method wiring
        # =====================================================================

        # /twins
        twins_resource = self.api.root.add_resource("twins")
        # POST /twins → admin (create twin)
        twins_resource.add_method(
            "POST", admin_integration, api_key_required=True,
        )
        # GET /twins → admin (list twins)
        twins_resource.add_method(
            "GET", admin_integration, api_key_required=True,
        )

        # /twins/{employeeId}
        twin_resource = twins_resource.add_resource("{employeeId}")
        # GET /twins/{employeeId} → admin (get twin detail)
        twin_resource.add_method(
            "GET", admin_integration, api_key_required=True,
        )
        # DELETE /twins/{employeeId} → admin (delete twin)
        twin_resource.add_method(
            "DELETE", admin_integration, api_key_required=True,
        )

        # /twins/{employeeId}/query
        query_resource = twin_resource.add_resource("query")
        # POST /twins/{employeeId}/query → query_handler
        query_resource.add_method(
            "POST", query_integration, api_key_required=True,
        )

        # /twins/{employeeId}/access
        access_resource = twin_resource.add_resource("access")
        # POST /twins/{employeeId}/access → admin (grant access)
        access_resource.add_method(
            "POST", admin_integration, api_key_required=True,
        )

        # /twins/{employeeId}/access/{userId}
        access_user_resource = access_resource.add_resource("{userId}")
        # DELETE /twins/{employeeId}/access/{userId} → admin (revoke access)
        access_user_resource.add_method(
            "DELETE", admin_integration, api_key_required=True,
        )

        # --- Stack Outputs ---
        CfnOutput(self, "ApiUrl", value=self.api.url)
        CfnOutput(self, "ApiKeyId", value=self.api_key.key_id)
        CfnOutput(
            self, "QueryHandlerFnArn",
            value=self.query_handler_fn.function_arn,
        )
        CfnOutput(
            self, "AdminFnArn",
            value=self.admin_fn.function_arn,
        )
