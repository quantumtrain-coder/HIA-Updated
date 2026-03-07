# 🩺 HIA (Health Insights Agent) - AWS AgentCore Edition

AI Agent to analyze blood reports and provide detailed health insights.
Runs on **AWS Bedrock AgentCore Runtime** with **DynamoDB** and **Bedrock API**.

## Architecture

- **Runtime**: Amazon Bedrock AgentCore Runtime (serverless, ARM64)
- **AI Models**: Amazon Bedrock (Claude 3.5 Sonnet → Haiku → Llama 3.2 → Llama 3.1)
- **Database**: Amazon DynamoDB (users, sessions, messages)
- **Auth**: Amazon Cognito
- **Frontend**: Streamlit (calls AgentCore Runtime via boto3)
- **Observability**: CloudWatch via AgentCore

## Project Structure

```
HIA-AgentCore/
├── agent/                    # AgentCore Runtime agent (backend)
│   ├── agent.py              # FastAPI app with /invocations and /ping
│   ├── services/
│   │   ├── bedrock_service.py    # Bedrock model manager with fallback
│   │   └── dynamodb_service.py   # DynamoDB data layer
│   ├── agents/
│   │   ├── analysis_agent.py     # Report analysis agent
│   │   └── chat_agent.py         # RAG chat agent (Bedrock-based)
│   ├── config/
│   │   ├── app_config.py
│   │   └── prompts.py
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                 # Streamlit UI (calls AgentCore)
│   ├── app.py
│   ├── requirements.txt
│   └── .streamlit/config.toml
├── infrastructure/
│   ├── dynamodb_tables.py    # DynamoDB table creation script
│   └── deploy_agent.py       # Deploy to AgentCore Runtime
└── README.md
```

## Quick Start

### 1. Create DynamoDB Tables
```bash
python infrastructure/dynamodb_tables.py
```

### 2. Deploy Agent to AgentCore Runtime
```bash
pip install bedrock-agentcore-starter-toolkit
cd agent
agentcore configure --entrypoint agent.py
agentcore launch
```

### 3. Run Frontend
```bash
cd frontend
pip install -r requirements.txt
streamlit run app.py
```

## Environment Variables

The agent uses IAM role credentials automatically when deployed to AgentCore.
For local development, configure AWS credentials via `aws configure` or environment variables.

| Variable | Description |
|----------|-------------|
| `AWS_REGION` | AWS region (default: us-east-1) |
| `COGNITO_USER_POOL_ID` | Cognito User Pool ID |
| `COGNITO_CLIENT_ID` | Cognito App Client ID |
| `AGENTCORE_RUNTIME_ARN` | AgentCore Runtime ARN (for frontend) |
