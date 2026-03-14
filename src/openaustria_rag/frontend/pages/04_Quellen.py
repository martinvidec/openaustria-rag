"""Streamlit page: Source management (SPEC-06 Section 3.4)."""

import streamlit as st

from openaustria_rag.frontend.app import get_client, init_session_state, render_sidebar

SOURCE_TYPE_ICONS = {"git": "🔗", "zip": "📦", "confluence": "📄"}


def main():
    init_session_state()
    render_sidebar()
    client = get_client()

    st.title("Quellen")

    project_id = st.session_state.current_project_id
    if not project_id:
        st.warning("Bitte zuerst ein Projekt auswählen.")
        return

    st.caption(f"Projekt: **{st.session_state.current_project_name}**")

    # Add source dialogs
    tab_git, tab_zip, tab_confluence = st.tabs(["Git Repository", "ZIP Upload", "Confluence"])

    with tab_git:
        with st.form("add_git"):
            name = st.text_input("Anzeigename", key="git_name")
            url = st.text_input("Repository URL", placeholder="https://github.com/org/repo.git")
            branch = st.text_input("Branch (optional)", placeholder="main")
            token = st.text_input("Access Token (optional)", type="password")
            if st.form_submit_button("Git-Quelle hinzufügen"):
                if url:
                    config = {"url": url}
                    if branch:
                        config["branch"] = branch
                    if token:
                        config["auth_token"] = token
                    try:
                        client.create_source(project_id, "git", name or url, config)
                        st.success("Git-Quelle hinzugefügt!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fehler: {e}")

    with tab_zip:
        with st.form("add_zip"):
            name = st.text_input("Anzeigename", key="zip_name")
            uploaded = st.file_uploader("ZIP-Datei", type=["zip"])
            if st.form_submit_button("ZIP hochladen"):
                if uploaded:
                    import os, tempfile
                    upload_dir = os.path.join("data", "uploads")
                    os.makedirs(upload_dir, exist_ok=True)
                    path = os.path.join(upload_dir, uploaded.name)
                    with open(path, "wb") as f:
                        f.write(uploaded.getbuffer())
                    try:
                        client.create_source(project_id, "zip", name or uploaded.name, {
                            "upload_path": path, "filename": uploaded.name,
                        })
                        st.success("ZIP-Quelle hinzugefügt!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fehler: {e}")

    with tab_confluence:
        with st.form("add_confluence"):
            name = st.text_input("Anzeigename", key="conf_name")
            base_url = st.text_input("Confluence URL", placeholder="https://company.atlassian.net")
            space_key = st.text_input("Space Key", placeholder="PROJ")
            email = st.text_input("E-Mail")
            api_token = st.text_input("API Token", type="password")

            col1, col2 = st.columns(2)
            add_clicked = col1.form_submit_button("Confluence-Quelle hinzufügen")

            if add_clicked and base_url and space_key and email and api_token:
                try:
                    client.create_source(project_id, "confluence", name or space_key, {
                        "base_url": base_url, "space_key": space_key,
                        "email": email, "api_token": api_token,
                    })
                    st.success("Confluence-Quelle hinzugefügt!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler: {e}")

    st.divider()

    # Source list
    try:
        sources = client.list_sources(project_id)
    except Exception as e:
        st.error(f"Fehler beim Laden: {e}")
        return

    if not sources:
        st.info("Noch keine Quellen hinzugefügt.")
        return

    STATUS_COLORS = {
        "configured": "🔵", "syncing": "🟡", "synced": "🟢", "error": "🔴",
    }

    for source in sources:
        icon = SOURCE_TYPE_ICONS.get(source["source_type"], "📁")
        status_icon = STATUS_COLORS.get(source["status"], "⚪")

        with st.container(border=True):
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])

            with col1:
                st.markdown(f"**{icon} {source['name']}**")
                st.caption(f"Typ: {source['source_type']} | Status: {status_icon} {source['status']}")
                if source.get("error_message"):
                    st.error(source["error_message"])
                if source.get("last_sync_at"):
                    st.caption(f"Letzter Sync: {source['last_sync_at'][:19]}")

            with col2:
                if st.button("Sync", key=f"sync_{source['id']}"):
                    try:
                        client.start_sync(source["id"])
                        st.info("Sync gestartet...")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fehler: {e}")

            with col3:
                if st.button("Test", key=f"test_{source['id']}"):
                    try:
                        result = client.test_connection(source["id"])
                        if result.get("success"):
                            st.success("Verbindung OK!")
                        else:
                            st.warning(f"Fehlgeschlagen: {result.get('error', '')}")
                    except Exception as e:
                        st.error(f"Fehler: {e}")

            with col4:
                if st.button("Entfernen", key=f"del_{source['id']}", type="secondary"):
                    try:
                        client.delete_source(source["id"])
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fehler: {e}")


if __name__ == "__main__":
    main()
