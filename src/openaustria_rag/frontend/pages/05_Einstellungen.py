"""Streamlit page: Settings (SPEC-06 Section 3.5)."""

import streamlit as st

from ..app import get_client, init_session_state, render_sidebar


def main():
    init_session_state()
    render_sidebar()
    client = get_client()

    st.title("Einstellungen")

    try:
        settings = client.get_settings()
    except Exception as e:
        st.error(f"Einstellungen konnten nicht geladen werden: {e}")
        return

    # Ollama
    st.subheader("Ollama LLM")
    col1, col2 = st.columns(2)
    with col1:
        ollama_url = st.text_input("Ollama URL", value=settings["ollama"]["base_url"])
        llm_model = st.text_input("LLM-Modell", value=settings["ollama"]["model"])
    with col2:
        temperature = st.slider(
            "Temperature", 0.0, 1.0,
            value=float(settings["ollama"]["temperature"]), step=0.05,
        )

        # Status check
        try:
            health = client.health_check()
            if health.get("ollama_available"):
                st.success("Ollama verbunden")
            else:
                st.warning("Ollama nicht erreichbar")
        except Exception:
            st.error("Backend nicht erreichbar")

    st.divider()

    # Embedding
    st.subheader("Embedding")
    col1, col2 = st.columns(2)
    with col1:
        emb_model = st.text_input("Embedding-Modell", value=settings["embedding"]["model"])
    with col2:
        emb_dim = st.number_input("Dimensionen", value=settings["embedding"]["dimensions"], disabled=True)

    st.divider()

    # Chunking
    st.subheader("Chunking")
    col1, col2, col3 = st.columns(3)
    with col1:
        code_max = st.number_input("Code max Tokens", value=settings["chunking"]["code_max_tokens"], step=256)
    with col2:
        doc_max = st.number_input("Doku max Tokens", value=settings["chunking"]["doc_max_tokens"], step=128)
    with col3:
        st.caption("Token-Limits bestimmen die maximale Größe einzelner Chunks.")

    st.divider()

    # Gap Analysis
    st.subheader("Gap-Analyse")
    name_threshold = st.slider(
        "Namens-Ähnlichkeit Threshold", 0.0, 1.0,
        value=float(settings["gap_analysis"]["name_similarity_threshold"]), step=0.05,
    )

    st.divider()

    if st.button("Einstellungen speichern", type="primary"):
        st.info("Einstellungen werden in der nächsten Version persistiert (config.yaml).")


if __name__ == "__main__":
    main()
