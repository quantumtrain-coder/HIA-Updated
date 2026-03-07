"""HIA Frontend - Streamlit UI that calls AgentCore Runtime agent."""

import streamlit as st
import boto3
import json
import os
import pdfplumber
from io import BytesIO

st.set_page_config(page_title="HIA - Health Insights Agent", page_icon="🩺", layout="wide")

REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_ARN = os.environ.get("AGENTCORE_RUNTIME_ARN", "")


def invoke_agent(action, **kwargs):
    """Call the AgentCore Runtime agent."""
    payload = {"action": action, **kwargs}

    # If AgentCore ARN is set, use AgentCore Runtime
    if AGENT_ARN:
        client = boto3.client("bedrock-agentcore", region_name=REGION)
        response = client.invoke_agent_runtime(
            agentRuntimeArn=AGENT_ARN,
            runtimeSessionId=st.session_state.get("runtime_session_id", "a" * 33),
            payload=json.dumps({"input": payload}),
        )
        body = json.loads(response["response"].read())
        return body.get("output", body)
    else:
        # Local mode: call agent directly via HTTP
        import requests
        resp = requests.post(
            "http://localhost:8080/invocations",
            json={"input": payload},
            timeout=120,
        )
        return resp.json().get("output", resp.json())


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
