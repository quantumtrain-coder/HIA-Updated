"""Chat agent using Bedrock for RAG-based follow-up questions."""

from services.bedrock_service import BedrockModelManager


class ChatAgent:
    """Handles follow-up questions about analyzed reports using Bedrock."""

    def __init__(self):
        self.model_manager = BedrockModelManager()

    def get_response(self, query, context_text, chat_history=None):
        """Get response using context and chat history (no vector store needed with large context windows)."""
        if chat_history is None:
            chat_history = []

        system_prompt = (
            "You are a medical assistant for question-answering tasks about blood reports. "
            "Use the provided report context to answer questions accurately. "
            "If you don't know the answer, say so. Keep answers concise."
        )

        # Build user message with context
        if context_text and context_text.strip():
            user_message = f"Report Context:\n{context_text[:8000]}\n\nQuestion: {query}"
        else:
            user_message = f"Question: {query}\n\nNote: No report context available."

        return self.model_manager.chat(system_prompt, user_message, chat_history)
