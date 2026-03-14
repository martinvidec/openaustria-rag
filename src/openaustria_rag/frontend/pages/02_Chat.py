"""Streamlit page: Chat interface with RAG integration (SPEC-06 Section 3.2)."""

import uuid

import streamlit as st

from openaustria_rag.frontend.app import get_client, init_session_state, render_sidebar


def main():
    init_session_state()
    render_sidebar()
    client = get_client()

    st.title("Chat")

    project_id = st.session_state.current_project_id
    if not project_id:
        st.warning("Bitte zuerst ein Projekt auswählen.")
        return

    st.caption(f"Projekt: **{st.session_state.current_project_name}**")

    # Ensure session ID
    if not st.session_state.chat_session_id:
        st.session_state.chat_session_id = str(uuid.uuid4())

    # Sidebar filters
    with st.sidebar:
        st.subheader("Filter")
        source_filter = st.selectbox(
            "Quelltyp",
            ["Alle", "Code", "Dokumentation", "Config"],
            key="chat_source_filter",
        )
        language_filter = st.selectbox(
            "Sprache",
            ["Alle", "Java", "Python", "TypeScript"],
            key="chat_lang_filter",
        )

        if st.button("Chat löschen"):
            st.session_state.chat_messages = []
            st.session_state.chat_session_id = str(uuid.uuid4())
            st.rerun()

    # Display chat history
    for msg in st.session_state.chat_messages:
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

    # Chat input
    if prompt := st.chat_input("Frage stellen..."):
        # Show user message
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Build filters
        filters = None
        if source_filter != "Alle":
            filter_map = {"Code": "code", "Dokumentation": "documentation", "Config": "config"}
            filters = {"source_type": filter_map.get(source_filter, source_filter.lower())}

        # Query API
        with st.chat_message("assistant"):
            with st.spinner("Suche und generiere Antwort..."):
                try:
                    result = client.query(
                        project_id=project_id,
                        query=prompt,
                        session_id=st.session_state.chat_session_id,
                    )

                    answer = result.get("answer", "Keine Antwort erhalten.")
                    st.markdown(answer)

                    sources = result.get("sources", [])
                    if sources:
                        with st.expander(f"Quellen ({len(sources)})"):
                            for src in sources:
                                st.markdown(
                                    f"- **{src.get('file_path', '')}** "
                                    f"({src.get('element_name', '')}) "
                                    f"Score: {src.get('score', 0):.3f}"
                                )

                    metrics = {
                        "retrieval_time_ms": result.get("retrieval_time_ms", 0),
                        "generation_time_ms": result.get("generation_time_ms", 0),
                        "token_count": result.get("token_count", 0),
                    }
                    cols = st.columns(3)
                    cols[0].metric("Retrieval", f"{metrics['retrieval_time_ms']:.0f}ms")
                    cols[1].metric("Generierung", f"{metrics['generation_time_ms']:.0f}ms")
                    cols[2].metric("Tokens", metrics["token_count"])

                    st.session_state.chat_messages.append({
                        "role": "assistant",
                        "content": answer,
                        "sources": sources,
                        "metrics": metrics,
                    })

                except Exception as e:
                    st.error(f"Fehler: {e}")
                    st.session_state.chat_messages.append({
                        "role": "assistant",
                        "content": f"Fehler: {e}",
                    })


if __name__ == "__main__":
    main()
