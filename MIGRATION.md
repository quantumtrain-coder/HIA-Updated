# HIA Migration: From Groq + Supabase to AWS-Native Architecture

## Overview

This document describes the migration of the [HIA (Health Insights Agent)](https://github.com/harshhh28/hia) application from a third-party service stack to a fully AWS-native architecture, deployed on [Amazon Bedrock AgentCore Runtime](https://aws.amazon.com/bedrock/agentcore/). The updated codebase is at [github.com/quantumtrain-coder/HIA-Updated](https://github.com/quantumtrain-coder/HIA-Updated).

## What Changed

| Component | Original | Updated |
|-----------|----------|---------|
| AI Models | Groq API (Llama 4 Maverick, Llama 3.3 70B, Llama 3.1 8B, Llama 3 70B) | Amazon Bedrock (Claude 3.5 Sonnet v2, Claude 3.5 Haiku, Llama 3.2 90B, Llama 3.1 8B) using cross-region inference profiles |
| Database | Supabase (PostgreSQL) | Amazon DynamoDB (3 tables: hia_users, hia_sessions, hia_messages) |
| Authentication | Supabase Auth | Custom auth with PBKDF2 password hashing stored in DynamoDB |
| RAG / Chat | Groq + LangChain + FAISS + HuggingFace embeddings | Bedrock with large context window (no vector store needed) |
| Runtime | Streamlit monolith (`streamlit run src/main.py`) | AgentCore Runtime (FastAPI container on ARM64) + Streamlit frontend |
| Deployment | Manual local run | Docker container → ECR → AgentCore Runtime via CodeBuild CI/CD |
| Configuration | `.streamlit/secrets.toml` with API keys | IAM roles and AWS credentials (no hardcoded secrets) |

## Architecture

The application was split into two components:

```
agent/          → FastAPI backend deployed to AgentCore Runtime
                  Exposes /invocations (POST) and /ping (GET)
                  Handles auth, sessions, analysis, and chat

frontend/       → Streamlit UI
                  Calls AgentCore Runtime via boto3 in production
                  Falls back to direct DynamoDB/Bedrock calls for local dev
```

## Key Decisions

**Why Bedrock instead of Groq?**
Bedrock runs within the AWS account with IAM-based access control. No external API keys to manage. Cross-region inference profiles provide automatic failover. Claude 3.5 Sonnet offers stronger medical analysis than the Llama models available on Groq.

**Why DynamoDB instead of Supabase?**
DynamoDB is serverless, pay-per-request, and stays within the AWS ecosystem. No external database credentials needed. The data model (users, sessions, messages) maps cleanly to DynamoDB's key-value pattern.

**Why remove the vector store (FAISS)?**
The original used LangChain + HuggingFace embeddings + FAISS for RAG-based chat. Claude 3.5 Sonnet has a 200K token context window, which is large enough to include the full blood report directly in the prompt. This eliminates the need for chunking, embedding, and retrieval — reducing complexity and dependencies significantly.

**Why AgentCore Runtime?**
AgentCore provides serverless, session-isolated execution with automatic scaling. Each user session runs in a dedicated microVM. No infrastructure to manage. The agent is packaged as a standard Docker container (ARM64) and deployed via ECR.

## Migration Steps

1. **Created DynamoDB tables** — `hia_users` (with email GSI), `hia_sessions` (with user_id GSI), `hia_messages` (partitioned by session_id, sorted by created_at). Run via `infrastructure/dynamodb_tables.py`.

2. **Replaced Groq with Bedrock** — Rewrote `model_manager.py` as `bedrock_service.py`. The model cascade uses `invoke_model` with provider-specific request/response formatting for Anthropic and Meta models. Automatic fallback on throttling or errors.

3. **Replaced Supabase with DynamoDB** — Rewrote `auth_service.py` as `dynamodb_service.py`. User passwords are hashed with PBKDF2-SHA256 with random salts. Sessions and messages use UUID primary keys with ISO timestamp sort keys.

4. **Simplified the chat agent** — Removed LangChain, FAISS, HuggingFace embeddings, and sentence-transformers. The chat agent now passes the report text directly in the Bedrock prompt context.

5. **Built the AgentCore agent** — Created `agent/agent.py` as a FastAPI app with `/invocations` and `/ping` endpoints. All actions (signup, login, create_session, analyze, chat) are routed through a single endpoint with an `action` field.

6. **Created the Dockerfile** — ARM64 container based on `python:3.11-slim-bookworm`. Installs FastAPI, uvicorn, boto3. Runs on port 8080 as required by AgentCore.

7. **Set up CI/CD** — CodeBuild project (`bedrock-agentcore-agent-builder`) builds the Docker image and pushes to ECR. Source is stored in S3. The buildspec handles ECR login, Docker build, tagging, and push.

8. **Updated the frontend** — The Streamlit frontend works in two modes: production (calls AgentCore Runtime via `AGENTCORE_RUNTIME_ARN` env var) and local development (calls DynamoDB and Bedrock directly).

## Dependencies Removed

The following packages from the original `requirements.txt` are no longer needed:

- `groq` — replaced by boto3 Bedrock calls
- `st-supabase-connection` — replaced by boto3 DynamoDB
- `gotrue` — Supabase auth library, no longer used
- `langchain`, `langchain-community`, `langchain-huggingface` — RAG framework, replaced by direct Bedrock context
- `faiss-cpu` — vector store, no longer needed
- `sentence-transformers` — embeddings, no longer needed
- `langchain-text-splitters` — text chunking, no longer needed

## New Dependencies

- `boto3` / `botocore` — AWS SDK
- `fastapi` / `uvicorn` — AgentCore Runtime web framework
- `pydantic` — request/response validation

## Running Locally

```bash
# Create DynamoDB tables (one-time)
python infrastructure/dynamodb_tables.py

# Start the frontend
cd frontend
pip install -r requirements.txt
streamlit run app.py
```

The frontend will use your local AWS credentials to talk to DynamoDB and Bedrock directly.

## Deploying to AgentCore

```bash
# Build and push via CodeBuild (automated)
# Or manually:
cd agent
docker build --platform linux/arm64 -t hia-agent .
docker tag hia-agent:latest <account>.dkr.ecr.us-east-1.amazonaws.com/bedrock-agentcore-agent:latest
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/bedrock-agentcore-agent:latest
python ../infrastructure/deploy_agent.py

# Set the ARN and run frontend
export AGENTCORE_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-east-1:<account>:runtime/hia-agent-xxx
streamlit run frontend/app.py
```
