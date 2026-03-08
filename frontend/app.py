"""HIA Frontend - Streamlit UI with DynamoDB + Bedrock (standalone or AgentCore)."""

import streamlit as st
import boto3
import json
import os
import uuid
import hashlib
import hmac
import pdfplumber
from io import BytesIO
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key

st.set_page_config(page_title="HIA - Health Insights Agent", page_icon="🩺", layout="wide")

REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_ARN = os.environ.get("AGENTCORE_RUNTIME_ARN", "")


# --- Direct DynamoDB + Bedrock for local/standalone mode ---

@st.cache_resource
def get_dynamodb():
    return boto3.resource("dynamodb", region_name=REGION)

@st.cache_resource
def get_bedrock():
    return boto3.client("bedrock-runtime", region_name=REGION)


def _hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(32).hex()
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
    return f"{salt}:{hashed}"


def _verify_password(password, stored_hash):
    salt, expected = stored_hash.split(":")
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000).hex()
    return hmac.compare_digest(expected, actual)


def _bedrock_generate(system_prompt, user_content):
    """Call Bedrock with model fallback."""
    client = get_bedrock()
    models = [
        "us.anthropic.claude-3-5-sonnet-20241022-v2:0",
        "us.anthropic.claude-3-5-haiku-20241022-v1:0",
    ]
    for model_id in models:
        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 2048,
                "temperature": 0.7,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}],
            })
            resp = client.invoke_model(modelId=model_id, body=body)
            result = json.loads(resp["body"].read())
            return {"success": True, "content": result["content"][0]["text"], "model_used": model_id}
        except Exception as e:
            continue
    return {"success": False, "error": "All models failed"}


def invoke_agent(action, **kwargs):
    """Route to AgentCore Runtime or handle locally with DynamoDB."""
    # If AgentCore ARN is set, use AgentCore Runtime
    if AGENT_ARN:
        payload = {"action": action, **kwargs}
        client = boto3.client("bedrock-agentcore", region_name=REGION)
        response = client.invoke_agent_runtime(
            agentRuntimeArn=AGENT_ARN,
            runtimeSessionId=st.session_state.get("runtime_session_id", "a" * 33),
            payload=json.dumps({"input": payload}),
        )
        body = json.loads(response["response"].read())
        return body.get("output", body)

    # --- Local/standalone mode: DynamoDB direct ---
    db = get_dynamodb()

    if action == "signup":
        table = db.Table("hia_users")
        # Check existing
        resp = table.query(IndexName="email-index", KeyConditionExpression=Key("email").eq(kwargs["email"]))
        if resp.get("Items"):
            return {"success": False, "error": "Email already registered"}
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        table.put_item(Item={
            "user_id": user_id, "email": kwargs["email"],
            "name": kwargs["name"], "password_hash": _hash_password(kwargs["password"]),
            "created_at": now,
        })
        return {"success": True, "data": {"id": user_id, "email": kwargs["email"], "name": kwargs["name"]}}

    if action == "login":
        table = db.Table("hia_users")
        resp = table.query(IndexName="email-index", KeyConditionExpression=Key("email").eq(kwargs["email"]))
        items = resp.get("Items", [])
        if not items:
            return {"success": False, "error": "User not found"}
        user = items[0]
        if not _verify_password(kwargs["password"], user["password_hash"]):
            return {"success": False, "error": "Invalid password"}
        return {"success": True, "data": {"id": user["user_id"], "email": user["email"], "name": user["name"]}}

    if action == "create_session":
        table = db.Table("hia_sessions")
        sid = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        title = kwargs.get("title") or f"{now.strftime('%d-%m-%Y')} | {now.strftime('%H:%M:%S')}"
        item = {"session_id": sid, "user_id": kwargs["user_id"], "title": title, "created_at": now.isoformat()}
        table.put_item(Item=item)
        return {"success": True, "session": {"id": sid, **item}}

    if action == "list_sessions":
        table = db.Table("hia_sessions")
        resp = table.query(IndexName="user_id-index", KeyConditionExpression=Key("user_id").eq(kwargs["user_id"]))
        sessions = sorted(resp.get("Items", []), key=lambda x: x.get("created_at", ""), reverse=True)
        return {"success": True, "sessions": sessions}

    if action == "delete_session":
        sid = kwargs["session_id"]
        msg_table = db.Table("hia_messages")
        msgs = msg_table.query(KeyConditionExpression=Key("session_id").eq(sid))
        with msg_table.batch_writer() as batch:
            for m in msgs.get("Items", []):
                batch.delete_item(Key={"session_id": m["session_id"], "created_at": m["created_at"]})
        db.Table("hia_sessions").delete_item(Key={"session_id": sid})
        return {"success": True}

    if action == "get_messages":
        table = db.Table("hia_messages")
        resp = table.query(KeyConditionExpression=Key("session_id").eq(kwargs["session_id"]))
        return {"success": True, "messages": resp.get("Items", [])}

    if action == "analyze":
        from config.prompts import SPECIALIST_PROMPTS
        system_prompt = SPECIALIST_PROMPTS["comprehensive_analyst"]
        data = f"Patient: {kwargs.get('patient_name')}, Age: {kwargs.get('age')}, Gender: {kwargs.get('gender')}\n\nReport:\n{kwargs.get('report', '')}"
        result = _bedrock_generate(system_prompt, data)
        if result["success"] and kwargs.get("session_id"):
            table = db.Table("hia_messages")
            now = datetime.now(timezone.utc).isoformat()
            table.put_item(Item={"session_id": kwargs["session_id"], "created_at": now, "message_id": str(uuid.uuid4()), "content": data[:500], "role": "user"})
            now2 = datetime.now(timezone.utc).isoformat()
            table.put_item(Item={"session_id": kwargs["session_id"], "created_at": now2, "message_id": str(uuid.uuid4()), "content": result["content"], "role": "assistant"})
        return {"success": result["success"], "analysis": result.get("content"), "model_used": result.get("model_used"), "error": result.get("error")}

    if action == "chat":
        system_prompt = "You are a medical assistant. Use the report context to answer questions. Be concise."
        context = kwargs.get("context", "")
        query = kwargs.get("query", "")
        user_msg = f"Report Context:\n{context[:8000]}\n\nQuestion: {query}" if context else f"Question: {query}"
        result = _bedrock_generate(system_prompt, user_msg)
        if result["success"] and kwargs.get("session_id"):
            table = db.Table("hia_messages")
            now = datetime.now(timezone.utc).isoformat()
            table.put_item(Item={"session_id": kwargs["session_id"], "created_at": now, "message_id": str(uuid.uuid4()), "content": query, "role": "user"})
            now2 = datetime.now(timezone.utc).isoformat()
            table.put_item(Item={"session_id": kwargs["session_id"], "created_at": now2, "message_id": str(uuid.uuid4()), "content": result["content"], "role": "assistant"})
        return {"success": result["success"], "response": result.get("content"), "error": result.get("error")}

    return {"success": False, "error": f"Unknown action: {action}"}


def extract_pdf_text(uploaded_file):
    """Extract text from uploaded PDF."""
    with pdfplumber.open(BytesIO(uploaded_file.read())) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def init_state():
    for key, default in [
        ("user", None), ("current_session", None),
        ("current_report_text", ""), ("page", "login"),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default


def show_login():
    st.title("🩺 HIA - Health Insights Agent")
    tab1, tab2 = st.tabs(["Login", "Sign Up"])

    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login", type="primary", use_container_width=True):
            result = invoke_agent("login", email=email, password=password)
            if result.get("success"):
                st.session_state.user = result["data"]
                st.session_state.page = "home"
                st.rerun()
            else:
                st.error(result.get("error", "Login failed"))

    with tab2:
        name = st.text_input("Name", key="signup_name")
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_pass")
        if st.button("Sign Up", type="primary", use_container_width=True):
            result = invoke_agent("signup", email=email, password=password, name=name)
            if result.get("success"):
                st.success("Account created. Please login.")
            else:
                st.error(result.get("error", "Signup failed"))


def show_sidebar():
    with st.sidebar:
        st.markdown(f"👋 Hi, {st.session_state.user.get('name', '')}")

        if st.button("➕ New Session", use_container_width=True):
            result = invoke_agent("create_session", user_id=st.session_state.user["id"])
            if result.get("success"):
                st.session_state.current_session = result["session"]
                st.rerun()

        st.markdown("---")
        result = invoke_agent("list_sessions", user_id=st.session_state.user["id"])
        if result.get("success"):
            for s in result.get("sessions", []):
                sid = s.get("session_id", s.get("id", ""))
                title = s.get("title", "Untitled")
                col1, col2 = st.columns([4, 1])
                with col1:
                    if st.button(f"📊 {title}", key=f"sess_{sid}", use_container_width=True):
                        st.session_state.current_session = {"id": sid, "title": title}
                        st.rerun()
                with col2:
                    if st.button("🗑️", key=f"del_{sid}"):
                        invoke_agent("delete_session", session_id=sid)
                        if st.session_state.current_session and st.session_state.current_session.get("id") == sid:
                            st.session_state.current_session = None
                        st.rerun()

        st.markdown("---")
        if st.button("Logout", use_container_width=True):
            st.session_state.user = None
            st.session_state.current_session = None
            st.session_state.page = "login"
            st.rerun()


def show_analysis_form():
    """Show the blood report analysis form."""
    st.subheader("📋 Upload Blood Report")

    col1, col2 = st.columns(2)
    with col1:
        patient_name = st.text_input("Patient Name")
        age = st.number_input("Age", min_value=0, max_value=150, value=30)
    with col2:
        gender = st.selectbox("Gender", ["Male", "Female", "Other"])

    uploaded_file = st.file_uploader("Upload PDF Report", type=["pdf"])
    manual_text = st.text_area("Or paste report text:", height=200)

    if st.button("🔍 Analyze Report", type="primary", use_container_width=True):
        report_text = manual_text
        if uploaded_file:
            with st.spinner("Extracting PDF..."):
                report_text = extract_pdf_text(uploaded_file)

        if not report_text.strip():
            st.error("Please upload a PDF or paste report text.")
            return

        st.session_state.current_report_text = report_text

        with st.spinner("Analyzing with Bedrock AI..."):
            session_id = st.session_state.current_session.get("id", "") if st.session_state.current_session else ""
            result = invoke_agent(
                "analyze",
                patient_name=patient_name,
                age=str(age),
                gender=gender,
                report=report_text,
                session_id=session_id,
            )

            if result.get("success"):
                st.success(f"Model: {result.get('model_used', 'N/A')}")
                st.markdown(result["analysis"])
            else:
                st.error(result.get("error", "Analysis failed"))


def show_chat(session_id):
    """Show chat history and input for follow-up questions."""
    result = invoke_agent("get_messages", session_id=session_id)
    if result.get("success"):
        for msg in result.get("messages", []):
            if msg.get("role") == "system":
                continue
            if msg["role"] == "user":
                st.info(msg["content"][:500])
            else:
                st.success(msg["content"])

    if prompt := st.chat_input("Ask a follow-up question..."):
        with st.spinner("Thinking..."):
            response = invoke_agent(
                "chat",
                query=prompt,
                context=st.session_state.get("current_report_text", ""),
                session_id=session_id,
            )
            if response.get("success"):
                st.success(response["response"])
            else:
                st.error(response.get("error", "Chat failed"))
            st.rerun()


def main():
    init_state()

    if not st.session_state.user:
        show_login()
        return

    show_sidebar()

    if st.session_state.current_session:
        st.title(f"📊 {st.session_state.current_session.get('title', 'Analysis')}")
        show_analysis_form()
        st.markdown("---")
        show_chat(st.session_state.current_session["id"])
    else:
        st.title("🩺 HIA - Health Insights Agent")
        st.markdown("Create a new session from the sidebar to get started.")


if __name__ == "__main__":
    main()
