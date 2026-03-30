#!/usr/bin/env python3
"""KnowledgeKeeper CDK application entry point."""
import os

import aws_cdk as cdk

from stacks import KKStorageStack, KKIngestionStack, KKQueryStack, KKFrontendStack


app = cdk.App()

# Resolve environment name from context or default
env_name = app.node.try_get_context("env") or app.node.try_get_context("default_environment") or "dev"
environments = app.node.try_get_context("environments") or {}
env_config = environments.get(env_name, {})

# AWS account and region from environment variables (never hardcoded)
aws_env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "eu-central-1"),
)

# Stack naming: KK{Layer}Stack{Environment} e.g. KKStorageStackDev
suffix = env_name.capitalize()

storage_stack = KKStorageStack(
    app,
    f"KKStorageStack{suffix}",
    env=aws_env,
)

ingestion_stack = KKIngestionStack(
    app,
    f"KKIngestionStack{suffix}",
    storage_stack=storage_stack,
    env=aws_env,
)
ingestion_stack.add_dependency(storage_stack)

query_stack = KKQueryStack(
    app,
    f"KKQueryStack{suffix}",
    storage_stack=storage_stack,
    ingestion_stack=ingestion_stack,
    env=aws_env,
)
query_stack.add_dependency(storage_stack)
query_stack.add_dependency(ingestion_stack)

frontend_stack = KKFrontendStack(
    app,
    f"KKFrontendStack{suffix}",
    api_url=query_stack.api.url,
    env=aws_env,
)
frontend_stack.add_dependency(query_stack)

app.synth()
