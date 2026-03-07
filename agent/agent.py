"""HIA AgentCore Runtime - FastAPI agent with /invocations and /ping endpoints."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional
from datetime import datetime, timezone

from agents.analysis_agent import AnalysisAgent
from agents.chat_agent import ChatAgent
from services.dynamodb_service import DynamoDBService
from config.prompts import SPECIALIST_PROMPTS

app = FastAPI(title="HIA - Health Insights Agent", version="2.0.0")

# Initialize services
db = DynamoDBService()
analysis_agent = AnalysisAgent()
chat_agent = ChatAgent()


class InvocationRequest(BaseModel):
    input: Dict[str, Any]


class InvocationResponse(BaseModel):
    output: Dict[str, Any]


@app.post("/invocations", response_model=InvocationResponse)
async def invoke(request: InvocationRequest):
    """Main agent invocation endpoint."""
    try:
        action = request.input.get("action", "")
        
        # --- Auth actions ---
        if action == "signup":
            ok, result = db.create_user(
                request.input["email"],
                request.input["password"],
                request.input["name"],
            )
            return InvocationResponse(output={"success": ok, "data": result if ok else None, "error": result if not ok else None})

        if action == "login":
            ok, result = db.authenticate_user(
                request.input["email"],
                request.input["password"],
            )
            return InvocationResponse(output={"success": ok, "data": result if ok else None, "error": result if not ok else None})

        # --- Session actions ---
        if action == "create_session":
            ok, session = db.create_session(
                request.input["user_id"],
                request.input.get("title"),
            )
            return InvocationResponse(output={"success": ok, "session": session})

        if action == "list_sessions":
            ok, sessions = db.get_user_sessions(request.input["user_id"])
            return InvocationResponse(output={"success": ok, "sessions": sessions})

        if action == "delete_session":
            ok, _ = db.delete_session(request.input["session_id"])
            return InvocationResponse(output={"success": ok})

        if action == "get_messages":
            ok, messages = db.get_session_messages(request.input["session_id"])
            return InvocationResponse(output={"success": ok, "messages": messages})

        # --- Analysis actions ---
        if action == "analyze":
            data = {
                "patient_name": request.input.get("patient_name", ""),
                "age": request.input.get("age", ""),
                "gender": request.input.get("gender", ""),
                "report": request.input.get("report", ""),
            }
            system_prompt = SPECIALIST_PROMPTS["comprehensive_analyst"]
            result = analysis_agent.analyze_report(data, system_prompt)

            # Save to DynamoDB if session provided
            session_id = request.input.get("session_id")
            if session_id and result["success"]:
                db.save_message(session_id, str(data), role="user")
                db.save_message(session_id, result["content"], role="assistant")

            return InvocationResponse(output={
                "success": result["success"],
                "analysis": result.get("content"),
                "model_used": result.get("model_used"),
                "error": result.get("error"),
            })

        # --- Chat actions ---
        if action == "chat":
            query = request.input.get("query", "")
            context = request.input.get("context", "")
            session_id = request.input.get("session_id")

            # Get chat history from DynamoDB
            chat_history = []
            if session_id:
                _, messages = db.get_session_messages(session_id)
                chat_history = [{"role": m["role"], "content": m["content"]} for m in messages]

            response = chat_agent.get_response(query, context, chat_history)

            # Save messages
            if session_id:
                db.save_message(session_id, query, role="user")
                db.save_message(session_id, response, role="assistant")

            return InvocationResponse(output={"success": True, "response": response})

        return InvocationResponse(output={"success": False, "error": f"Unknown action: {action}"})

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ping")
async def ping():
    """Health check endpoint required by AgentCore Runtime."""
    return {"status": "healthy", "service": "HIA", "timestamp": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
