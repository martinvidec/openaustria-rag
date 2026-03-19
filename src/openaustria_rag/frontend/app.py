"""Streamlit main application (SPEC-06 Section 2)."""

import streamlit as st

from openaustria_rag.frontend.api_client import APIClient

API_URL = "http://localhost:8000"


def get_client() -> APIClient:
    if "api_client" not in st.session_state:
        st.session_state.api_client = APIClient(API_URL)
    return st.session_state.api_client


def init_session_state():
    defaults = {
        "current_project_id": None,
        "current_project_name": None,
        "chat_session_id": None,
        "chat_messages": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def render_sidebar():
    """Sidebar with project selector and Ollama status."""
    client = get_client()

    st.sidebar.title("OpenAustria RAG")

    # Ollama status
    try:
        health = client.health_check()
        if health.get("ollama_available"):
            st.sidebar.success("Ollama: Verbunden")
        else:
            st.sidebar.warning("Ollama: Nicht erreichbar")
    except Exception:
        st.sidebar.error("Backend nicht erreichbar")

    st.sidebar.divider()

    # Project selector
    try:
        projects = client.list_projects()
    except Exception:
        projects = []

    if projects:
        project_names = {p["id"]: p["name"] for p in projects}
        options = list(project_names.keys())
        labels = [f"{project_names[pid]} ({next((p['status'] for p in projects if p['id'] == pid), '')})" for pid in options]

        current_idx = 0
        if st.session_state.current_project_id in options:
            current_idx = options.index(st.session_state.current_project_id)

        selected = st.sidebar.selectbox(
            "Projekt",
            options=options,
            format_func=lambda pid: next(
                (l for o, l in zip(options, labels) if o == pid), pid
            ),
            index=current_idx,
        )
        st.session_state.current_project_id = selected
        st.session_state.current_project_name = project_names.get(selected, "")
    else:
        st.sidebar.info("Keine Projekte vorhanden")


def main():
    st.set_page_config(
        page_title="OpenAustria RAG",
        page_icon="📚",
        layout="wide",
    )
    init_session_state()
    render_sidebar()

    st.title("OpenAustria RAG")
    st.markdown(
        "Dokumentationsplattform mit RAG-basierter Suche und "
        "automatischer Gap-Analyse zwischen Code und Dokumentation."
    )

    client = get_client()

    # Quick status overview
    try:
        health = client.health_check()
        projects = client.list_projects()
    except Exception:
        st.error("Backend nicht erreichbar. Ist der API-Server gestartet?")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Projekte", len(projects))
    col2.metric("Ollama", "Verbunden" if health.get("ollama_available") else "Offline")
    col3.metric("Datenbank", "OK" if health.get("database_ok") else "Fehler")

    if not projects:
        st.info("Erstelle ein Projekt unter **Projekte** um loszulegen.")
    else:
        st.markdown("### Projekte")
        for p in projects:
            st.markdown(f"- **{p['name']}** ({p['status']})")


if __name__ == "__main__":
    main()
