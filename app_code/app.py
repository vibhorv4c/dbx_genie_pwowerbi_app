import os
import re
import json
import pandas as pd
import streamlit as st
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
from databricks.sdk import WorkspaceClient

# ---------- Page setup ----------
st.set_page_config(layout="wide")
st.title("Data Intelligence Portal")

# ---------- Databricks SDK client ----------
w = WorkspaceClient()

# ---------- Config ----------
GENIE_SPACE_ID = os.getenv("GENIE_SPACE_ID", "").strip()
PBI_SECURE_EMBED_URL = os.getenv("PBI_SECURE_EMBED_URL", "").strip()

# ---------- Utilities for Secure Embed ----------
def _extract_src_from_iframe(iframe_or_url: str) -> str:
    txt = (iframe_or_url or "").strip()
    if not txt:
        return ""
    m = re.search(r'src="\'["\']', txt, flags=re.IGNORECASE)
    return m.group(1) if m else txt

def _append_url_params(url: str, extra: dict) -> str:
    if not url:
        return url
    parts = list(urlparse(url))
    q = dict(parse_qsl(parts[4], keep_blank_values=True))
    for k, v in (extra or {}).items():
        if v is not None and v != "":
            q[k] = v
    parts[4] = urlencode(q, doseq=True)
    return urlunparse(parts)

def render_powerbi_secure_embed(secure_embed_url_or_iframe: str,
                                page_name: str = "",
                                filter_expr: str = "",
                                theme: str = "",
                                height: int = 650):
    """
    Renders a Power BI report using 'Secure Embed' (requires sign-in; RLS & permissions apply).
    Docs: https://learn.microsoft.com/power-bi/collaborate-share/service-embed-secure
    """
    base_url = _extract_src_from_iframe(secure_embed_url_or_iframe)

    params = {}
    if page_name:
        params["pageName"] = page_name
    if filter_expr:
        params["filter"] = filter_expr
    if theme in ("light", "dark"):
        params["theme"] = theme

    final_url = _append_url_params(base_url, params) if base_url else ""

    if not final_url:
        st.info("Paste your **Secure Embed** link or the full `<iframe>` snippet from Power BI.")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        st.caption("Secure Embed requires users to authenticate and honors RLS & permissions.")
    with col2:
        st.link_button("Open in Power BI", final_url)

    st.components.v1.iframe(src=final_url, height=height)

# ---------- Genie helpers ----------
def _display_genie_message(msg_content=None, df=None, sql=None):
    if msg_content:
        st.markdown(msg_content)
    if df is not None:
        st.dataframe(df, use_container_width=True)
    if sql:
        with st.expander("Show generated SQL"):
            st.code(sql, language="sql")

def _get_statement_dataframe(statement_id: str) -> pd.DataFrame:
    result = w.statement_execution.get_statement(statement_id)
    cols = [c.name for c in result.manifest.schema.columns]
    return pd.DataFrame(result.result.data_array, columns=cols)

def process_genie_response(response):
    if not response or not response.attachments:
        st.info("No response attachments returned.")
        return
    for att in response.attachments:
        if getattr(att, "text", None) and att.text.content:
            _display_genie_message(msg_content=att.text.content)
        elif getattr(att, "query", None):
            stmt_id = response.query_result.statement_id
            df = _get_statement_dataframe(stmt_id)
            _display_genie_message(
                msg_content=att.query.description,
                df=df,
                sql=att.query.query,
            )

def genie_chat_ui():
    st.subheader("Ask Anything (Genie)")
    if not GENIE_SPACE_ID:
        st.warning("Set GENIE_SPACE_ID in app.yaml env or enter it below.")
    space_id = st.text_input("Genie Space ID", value=GENIE_SPACE_ID, help="Copy from Genie URL: rooms/<SPACE-ID>?o=...")

    if "conversation_id" not in st.session_state:
        st.session_state.conversation_id = None

    prompt = st.chat_input("Ask your question about the data…")
    if prompt and space_id:
        st.chat_message("user").markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Genie is working…"):
                if st.session_state.conversation_id:
                    conv = w.genie.create_message_and_wait(space_id, st.session_state.conversation_id, prompt)
                else:
                    conv = w.genie.start_conversation_and_wait(space_id, prompt)
                    st.session_state.conversation_id = conv.conversation_id
                process_genie_response(conv)

# ---------- Power BI panel (Secure Embed only) ----------
def power_bi_panel_secure_only():
    st.subheader("Executive Dashboard (Power BI — Secure Embed)")

    user_input = st.text_area(
        "Paste the **Secure Embed** link or the `<iframe>` snippet from Power BI (NOT 'Publish to web')",
        value=PBI_SECURE_EMBED_URL,
        height=80,
        placeholder="https://app.powerbi.com/reportEmbed?reportId=...&groupId=...&autoAuth=true&ctid=..."
    )

    with st.expander("Optional settings (URL parameters)"):
        c1, c2, c3 = st.columns([1, 1, 1])
        with c1:
            page_name = st.text_input("pageName", placeholder="e.g., ReportSection123")
        with c2:
            theme = st.selectbox("theme", options=["", "light", "dark"], index=0)
        with c3:
            height = st.number_input("Height (px)", min_value=400, max_value=1600, value=650, step=50)

        filter_expr = st.text_input("URL filter (optional)", placeholder="e.g., Sales/Region eq 'West'")

    render_powerbi_secure_embed(
        secure_embed_url_or_iframe=user_input,
        page_name=page_name,
        filter_expr=filter_expr,
        theme=theme,
        height=height
    )

# ---------- Layout ----------
left, right = st.columns([2, 1])
with left:
    power_bi_panel_secure_only()
with right:
    genie_chat_ui()

st.caption(
    "ℹ️ Secure Embed enforces sign-in and respects RLS/permissions; avoid 'Publish to web' for private data."
)

