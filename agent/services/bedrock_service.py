"""Bedrock model manager with multi-model fallback cascade."""

import boto3
import json
import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class ModelTier(Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    TERTIARY = "tertiary"
    FALLBACK = "fallback"


class BedrockModelManager:
    """Manages Bedrock model selection and fallback using cross-region inference profiles."""

    MODEL_CONFIG = {
        ModelTier.PRIMARY: {
            "model_id": "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            "max_tokens": 2048,
            "temperature": 0.7,
            "provider": "anthropic",
        },
        ModelTier.SECONDARY: {
            "model_id": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            "max_tokens": 2048,
            "temperature": 0.7,
            "provider": "anthropic",
        },
        ModelTier.TERTIARY: {
            "model_id": "us.meta.llama3-2-90b-instruct-v1:0",
            "max_tokens": 2048,
            "temperature": 0.7,
            "provider": "meta",
        },
        ModelTier.FALLBACK: {
            "model_id": "us.meta.llama3-1-8b-instruct-v1:0",
            "max_tokens": 2048,
            "temperature": 0.7,
            "provider": "meta",
        },
    }

    def __init__(self, region="us-east-1"):
        self.client = boto3.client("bedrock-runtime", region_name=region)

    def _invoke_model(self, model_config, system_prompt, user_content):
        """Invoke a Bedrock model based on provider type."""
        provider = model_config["provider"]
        model_id = model_config["model_id"]

        if provider == "anthropic":
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": model_config["max_tokens"],
                "temperature": model_config["temperature"],
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}],
            })
        elif provider == "meta":
            body = json.dumps({
                "prompt": f"<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n{system_prompt}<|eot_id|><|start_header_id|>user<|end_header_id|>\n{user_content}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n",
                "max_gen_len": model_config["max_tokens"],
                "temperature": model_config["temperature"],
            })
        else:
            raise ValueError(f"Unsupported provider: {provider}")

        response = self.client.invoke_model(modelId=model_id, body=body)
        response_body = json.loads(response["body"].read())

        if provider == "anthropic":
            return response_body["content"][0]["text"]
        elif provider == "meta":
            return response_body["generation"]

    def generate(self, system_prompt, user_content, retry_count=0):
        """Generate response with automatic model fallback."""
        if retry_count > 3:
            return {"success": False, "error": "All models failed after retries"}

        tiers = [ModelTier.PRIMARY, ModelTier.SECONDARY, ModelTier.TERTIARY, ModelTier.FALLBACK]
        tier = tiers[min(retry_count, len(tiers) - 1)]
        config = self.MODEL_CONFIG[tier]

        try:
            logger.info(f"Attempting {config['model_id']} (tier: {tier.value})")
            content = self._invoke_model(config, system_prompt, user_content)
            return {
                "success": True,
                "content": content,
                "model_used": config["model_id"],
            }
        except Exception as e:
            error_msg = str(e).lower()
            logger.warning(f"Model {config['model_id']} failed: {error_msg}")
            if "throttl" in error_msg or "rate" in error_msg:
                time.sleep(2)
            return self.generate(system_prompt, user_content, retry_count + 1)

    def chat(self, system_prompt, user_message, chat_history=None):
        """Chat completion with conversation history (Anthropic models only)."""
        messages = []
        if chat_history:
            for msg in chat_history[-6:]:
                if msg["role"] in ("user", "assistant"):
                    messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "temperature": 0.7,
            "system": system_prompt,
            "messages": messages,
        })

        try:
            response = self.client.invoke_model(
                modelId=self.MODEL_CONFIG[ModelTier.SECONDARY]["model_id"],
                body=body,
            )
            result = json.loads(response["body"].read())
            return result["content"][0]["text"]
        except Exception as e:
            return f"Error: {str(e)}"
