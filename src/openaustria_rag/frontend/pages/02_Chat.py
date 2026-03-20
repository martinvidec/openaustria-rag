"""Streamlit page: Chat interface with streaming RAG (SPEC-06 Section 3.2)."""

import uuid

import streamlit as st

from openaustria_rag.frontend.Dashboard import get_client, init_session_state, render_sidebar


def _render_metrics(m: dict, model: str):
    """Render chat metrics as a compact single-line caption."""
    parts = [
        f"**{m.get('model', model)}**",
        f"Retrieval {m.get('retrieval_time_ms', 0):.0f}ms",
        f"Generierung {m.get('generation_time_ms', 0):.1f}s",
        f"{m.get('token_count', 0)} Tokens",
        f"{m.get('tokens_per_second', 0):.1f} tok/s",
    ]
    st.caption(" · ".join(parts))


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

    # Load current model name for display in metrics
    try:
        _settings = client.get_settings()
        active_model = _settings["ollama"]["model"]
    except Exception:
        active_model = "?"

    if not st.session_state.chat_session_id:
        st.session_state.chat_session_id = str(uuid.uuid4())

    # Sidebar controls
    with st.sidebar:
        st.subheader("Chat-Einstellungen")
        use_streaming = st.toggle("Streaming", value=True, help="Antwort Wort für Wort anzeigen")
        top_k = st.slider("Quellen (top_k)", 1, 30, 15, help="Anzahl der abgerufenen Kontextquellen. ContextBudget begrenzt automatisch was in den Prompt passt.")

        st.divider()
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
                    for i, src in enumerate(msg["sources"], 1):
                        icon = {"documentation": "📄", "code": "💻", "config": "⚙️"}.get(src.get("source_type", ""), "📁")
                        score = f" ({src['score']:.3f})" if "score" in src else ""
                        st.markdown(f"{i}. {icon} `{src.get('file_path', 'unbekannt')}`{score}")
            if msg.get("metrics"):
                _render_metrics(msg["metrics"], active_model)

    # Chat input
    if prompt := st.chat_input("Frage stellen..."):
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            if use_streaming:
                _handle_streaming(client, project_id, prompt, top_k, active_model)
            else:
                _handle_blocking(client, project_id, prompt, top_k, active_model)


def _handle_streaming(client, project_id, prompt, top_k, active_model):
    """Stream tokens word by word."""
    placeholder = st.empty()
    full_response = ""
    metrics = {}
    sources = []

    # Show retrieval indicator before first event arrives
    placeholder.markdown("_Suche relevante Dokumente..._")

    try:
        for event in client.query_stream(project_id, prompt, top_k=top_k):
            if event["type"] == "sources":
                metrics["retrieval_time_ms"] = event.get("retrieval_time_ms", 0)
                sources = event.get("sources", [])
                placeholder.markdown("_Generiere Antwort..._")
            elif event["type"] == "token":
                full_response += event["content"]
                placeholder.markdown(full_response + "▌")
            elif event["type"] == "done":
                metrics["token_count"] = event.get("token_count", 0)
                metrics["generation_time_ms"] = event.get("generation_time_ms", 0) / 1000
                metrics["tokens_per_second"] = event.get("tokens_per_second", 0)

        placeholder.markdown(full_response)

        if sources:
            with st.expander(f"Quellen ({len(sources)})"):
                for i, src in enumerate(sources, 1):
                    st.markdown(f"{i}. `{src.get('file_path', 'unbekannt')}`")

        if metrics:
            metrics["model"] = active_model
            _render_metrics(metrics, active_model)

        st.session_state.chat_messages.append({
            "role": "assistant",
            "content": full_response,
            "sources": sources,
            "metrics": metrics,
        })

    except Exception as e:
        st.error(f"Fehler: {e}")
        st.session_state.chat_messages.append({
            "role": "assistant", "content": f"Fehler: {e}",
        })


def _handle_blocking(client, project_id, prompt, top_k, active_model):
    """Non-streaming query with spinner."""
    with st.spinner("Suche und generiere Antwort..."):
        try:
            result = client.query(
                project_id=project_id, query=prompt,
                session_id=st.session_state.chat_session_id,
                top_k=top_k,
            )
            answer = result.get("answer", "Keine Antwort.")
            st.markdown(answer)

            gen_s = result.get("generation_time_ms", 0) / 1000
            tokens = result.get("token_count", 0)
            tps = tokens / gen_s if gen_s > 0 else 0

            metrics = {
                "model": active_model,
                "retrieval_time_ms": result.get("retrieval_time_ms", 0),
                "generation_time_ms": gen_s,
                "token_count": tokens,
                "tokens_per_second": tps,
            }
            _render_metrics(metrics, active_model)

            st.session_state.chat_messages.append({
                "role": "assistant", "content": answer, "metrics": metrics,
            })
        except Exception as e:
            st.error(f"Fehler: {e}")


if __name__ == "__main__":
    main()
