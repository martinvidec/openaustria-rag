"""Streamlit page: Settings (SPEC-06 Section 3.5)."""

import streamlit as st

from openaustria_rag.frontend.app import get_client, init_session_state, render_sidebar


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

        # Model selector — try to load available models from Ollama
        # Filter out embedding-only models that aren't suitable for chat/generation
        EMBEDDING_MODELS = {"nomic-embed-text"}
        available_models = [settings["ollama"]["model"]]
        try:
            import requests
            resp = requests.get(f"{settings['ollama']['base_url']}/api/tags", timeout=5)
            if resp.ok:
                models = [
                    m["name"] for m in resp.json().get("models", [])
                    if not any(m["name"].startswith(emb) for emb in EMBEDDING_MODELS)
                ]
                if models:
                    available_models = models
        except Exception:
            pass

        current_model = settings["ollama"]["model"]
        model_idx = 0
        for i, m in enumerate(available_models):
            if m.startswith(current_model):
                model_idx = i
                break

        llm_model = st.selectbox("LLM-Modell", available_models, index=model_idx)
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

    # Embedding (read-only — fixed to nomic-embed-text for consistent vector dimensions)
    st.subheader("Embedding")
    col1, col2 = st.columns(2)
    with col1:
        emb_model = st.text_input("Embedding-Modell", value=settings["embedding"]["model"], disabled=True)
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
        try:
            client.update_settings(
                ollama={"base_url": ollama_url, "model": llm_model, "temperature": temperature},
                chunking={"code_max_tokens": code_max, "doc_max_tokens": doc_max},
                gap_analysis={"name_similarity_threshold": name_threshold},
            )
            st.success("Einstellungen gespeichert (config.yaml).")
        except Exception as e:
            st.error(f"Fehler beim Speichern: {e}")


if __name__ == "__main__":
    main()
