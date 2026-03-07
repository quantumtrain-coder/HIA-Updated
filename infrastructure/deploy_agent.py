"""Deploy HIA agent to AgentCore Runtime."""

import boto3
import json

ACCOUNT_ID = "085794773476"
REGION = "us-east-1"
AGENT_NAME = "hia-health-insights-agent"
ECR_REPO = f"{ACCOUNT_ID}.dkr.ecr.{REGION}.amazonaws.com/hia-agent:latest"
ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/HIAAgentCoreRole"


def deploy():
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)

    response = client.create_agent_runtime(
        agentRuntimeName=AGENT_NAME,
        agentRuntimeArtifact={
            "containerConfiguration": {"containerUri": ECR_REPO}
        },
        networkConfiguration={"networkMode": "PUBLIC"},
        roleArn=ROLE_ARN,
        lifecycleConfiguration={
            "idleRuntimeSessionTimeout": 300,
            "maxLifetime": 1800,
        },
    )

    print(f"Agent deployed successfully!")
    print(f"ARN: {response['agentRuntimeArn']}")
    print(f"Status: {response['status']}")
    return response


if __name__ == "__main__":
    deploy()
