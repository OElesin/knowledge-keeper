from aws_cdk import Stack
from constructs import Construct


class KKQueryStack(Stack):
    """Query layer: API Gateway, query + admin Lambda functions."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # Implemented in Phase 3
