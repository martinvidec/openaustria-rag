"""Chat message display component."""

import streamlit as st


def render_chat_message(msg: dict):
    """Render a single chat message with optional sources and metrics."""
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        if msg.get("sources"):
            with st.expander(f"Quellen ({len(msg['sources'])})"):
                for src in msg["sources"]:
                    st.markdown(
                        f"- **{src.get('file_path', '')}** "
                        f"({src.get('element_name', '')}) "
                        f"Score: {src.get('score', 0):.3f}"
                    )

        if msg.get("metrics"):
            m = msg["metrics"]
            cols = st.columns(3)
            cols[0].metric("Retrieval", f"{m.get('retrieval_time_ms', 0):.0f}ms")
            cols[1].metric("Generierung", f"{m.get('generation_time_ms', 0):.0f}ms")
            cols[2].metric("Tokens", m.get("token_count", 0))
