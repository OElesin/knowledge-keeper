"""KKFrontendStack: S3 + CloudFront for hosting the React SPA."""
from pathlib import Path

from aws_cdk import (
    Stack,
    CfnOutput,
    RemovalPolicy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
)
from constructs import Construct


class KKFrontendStack(Stack):
    """Frontend hosting: S3 bucket + CloudFront distribution.

    Deploys the built Vite assets from ``frontend/dist/`` to S3 and
    serves them through CloudFront with HTTPS and SPA routing support.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        api_url: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        env_name = (
            self.node.try_get_context("env")
            or self.node.try_get_context("default_environment")
            or "dev"
        )

        # --- S3 bucket for frontend assets ---
        self.frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            bucket_name=f"kk-{self.account}-{env_name}-frontend",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # --- CloudFront distribution ---
        self.distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment=f"KnowledgeKeeper {env_name} frontend",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    self.frontend_bucket,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            default_root_object="index.html",
            # SPA routing: return index.html for 403/404 so React Router handles paths
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=403,
                    response_page_path="/index.html",
                    response_http_status=200,
                ),
                cloudfront.ErrorResponse(
                    http_status=404,
                    response_page_path="/index.html",
                    response_http_status=200,
                ),
            ],
        )

        # --- Deploy built assets from frontend/dist/ ---
        dist_path = str(
            Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
        )

        s3deploy.BucketDeployment(
            self,
            "DeployFrontend",
            sources=[s3deploy.Source.asset(dist_path)],
            destination_bucket=self.frontend_bucket,
            distribution=self.distribution,
            distribution_paths=["/*"],
        )

        # --- Outputs ---
        CfnOutput(
            self,
            "FrontendUrl",
            value=f"https://{self.distribution.distribution_domain_name}",
            description="CloudFront URL for the frontend",
        )
        CfnOutput(
            self,
            "DistributionId",
            value=self.distribution.distribution_id,
        )
        CfnOutput(
            self,
            "FrontendBucketName",
            value=self.frontend_bucket.bucket_name,
        )
