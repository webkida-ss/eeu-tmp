"""AWS Lambda entrypoint: wraps the FastAPI app with Mangum.

Deployed behind an API Gateway HTTP API (payload format 2.0), which Mangum
handles natively. Built into the deployment zip by scripts/build_lambda.sh.

The DynamoDB store factory applies the SDK default credential chain outside
DynamoDB Local, so this entrypoint imports the application without rewriting
storage factories.
"""

from __future__ import annotations

from main import app
from mangum import Mangum

handler = Mangum(app)
