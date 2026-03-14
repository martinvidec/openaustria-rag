"""Streamlit page: Project management (SPEC-06 Section 3.1)."""

import streamlit as st

from openaustria_rag.frontend.app import get_client, init_session_state, render_sidebar


def main():
    init_session_state()
    render_sidebar()
    client = get_client()

    st.title("Projekte")

    # New project dialog
    with st.expander("Neues Projekt erstellen", expanded=False):
        with st.form("new_project"):
            name = st.text_input("Name", max_chars=100)
            description = st.text_area("Beschreibung")
            submitted = st.form_submit_button("Erstellen")
            if submitted and name:
                try:
                    project = client.create_project(name, description)
                    st.session_state.current_project_id = project["id"]
                    st.session_state.current_project_name = project["name"]
                    st.success(f"Projekt '{name}' erstellt!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler: {e}")

    st.divider()

    # Project list
    try:
        projects = client.list_projects()
    except Exception as e:
        st.error(f"Fehler beim Laden: {e}")
        return

    if not projects:
        st.info("Keine Projekte vorhanden. Erstelle dein erstes Projekt oben.")
        return

    STATUS_ICONS = {
        "created": "🔵",
        "indexing": "🟡",
        "ready": "🟢",
        "error": "🔴",
    }

    for project in projects:
        icon = STATUS_ICONS.get(project["status"], "⚪")
        is_current = project["id"] == st.session_state.current_project_id

        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 1, 1])

            with col1:
                st.subheader(f"{icon} {project['name']}")
                if project["description"]:
                    st.caption(project["description"])
                st.caption(f"Status: {project['status']} | Erstellt: {project['created_at'][:10]}")

            with col2:
                if st.button("Öffnen", key=f"open_{project['id']}"):
                    st.session_state.current_project_id = project["id"]
                    st.session_state.current_project_name = project["name"]
                    st.rerun()

            with col3:
                if st.button("Löschen", key=f"del_{project['id']}", type="secondary"):
                    try:
                        client.delete_project(project["id"])
                        if st.session_state.current_project_id == project["id"]:
                            st.session_state.current_project_id = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fehler: {e}")


if __name__ == "__main__":
    main()
