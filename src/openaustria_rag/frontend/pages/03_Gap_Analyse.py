"""Streamlit page: Gap analysis dashboard (SPEC-06 Section 3.3)."""

import json

import streamlit as st

from openaustria_rag.frontend.app import get_client, init_session_state, render_sidebar

SEVERITY_BADGES = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🔵",
    "low": "⚪",
}

GAP_TYPE_LABELS = {
    "undocumented": "Nicht dokumentiert",
    "unimplemented": "Nicht implementiert",
    "divergent": "Abweichend",
    "consistent": "Konsistent",
}


def main():
    init_session_state()
    render_sidebar()
    client = get_client()

    st.title("Gap-Analyse")

    project_id = st.session_state.current_project_id
    if not project_id:
        st.warning("Bitte zuerst ein Projekt auswählen.")
        return

    st.caption(f"Projekt: **{st.session_state.current_project_name}**")

    # Load latest report first to show status
    try:
        report = client.get_latest_gap_report(project_id)
    except Exception as e:
        st.error(f"Fehler: {e}")
        report = None

    # Start analysis button
    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("Analyse starten", type="primary"):
            try:
                client.start_gap_analysis(project_id)
                st.info(
                    "Gap-Analyse wurde im Hintergrund gestartet. "
                    "Dies kann je nach Projektgröße einige Minuten dauern. "
                    "Klicke auf **Ergebnisse aktualisieren** um den Status zu prüfen."
                )
            except Exception as e:
                st.error(f"Fehler: {e}")
    with col2:
        if st.button("Ergebnisse aktualisieren"):
            st.rerun()

    st.divider()

    if not report:
        st.info("Noch keine Gap-Analyse durchgeführt. Starte eine Analyse oben.")
        return

    # Summary metrics
    summary = report.get("summary", {})
    st.subheader("Übersicht")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Code-Elemente", summary.get("total_code_elements", 0))
    col2.metric("Dokumentiert", summary.get("documented", 0))
    col3.metric("Nicht dokumentiert", summary.get("undocumented", 0))
    col4.metric("Abweichend", summary.get("divergent", 0))

    # Coverage bar
    coverage = summary.get("documentation_coverage", 0)
    st.progress(min(coverage, 1.0), text=f"Dokumentations-Abdeckung: {coverage:.0%}")

    st.divider()

    # Filters
    gaps = report.get("gaps", [])
    if not gaps:
        st.success("Keine Gaps gefunden!")
        return

    st.subheader(f"Gaps ({len(gaps)})")

    col1, col2, col3 = st.columns(3)
    with col1:
        type_filter = st.selectbox("Typ", ["Alle", "Nicht dokumentiert", "Abweichend", "Nicht implementiert", "Konsistent"])
    with col2:
        sev_filter = st.selectbox("Schweregrad", ["Alle", "Critical", "High", "Medium", "Low"])
    with col3:
        search = st.text_input("Suche", placeholder="Element-Name...")

    # Apply filters
    type_map = {"Nicht dokumentiert": "undocumented", "Abweichend": "divergent",
                "Nicht implementiert": "unimplemented", "Konsistent": "consistent"}
    sev_map = {"Critical": "critical", "High": "high", "Medium": "medium", "Low": "low"}

    filtered = gaps
    if type_filter != "Alle":
        filtered = [g for g in filtered if g["gap_type"] == type_map.get(type_filter)]
    if sev_filter != "Alle":
        filtered = [g for g in filtered if g["severity"] == sev_map.get(sev_filter)]
    if search:
        search_lower = search.lower()
        filtered = [g for g in filtered if search_lower in g.get("code_element_name", "").lower()
                    or search_lower in g.get("file_path", "").lower()]

    st.caption(f"{len(filtered)} von {len(gaps)} Gaps angezeigt")

    # Gap list
    for gap in filtered:
        sev_icon = SEVERITY_BADGES.get(gap["severity"], "⚪")
        gap_label = GAP_TYPE_LABELS.get(gap["gap_type"], gap["gap_type"])
        fp = gap.get("is_false_positive", False)

        with st.container(border=True):
            col1, col2, col3 = st.columns([4, 1, 1])

            with col1:
                title = f"{sev_icon} **{gap.get('code_element_name', 'Unknown')}**"
                if fp:
                    title += " ~~(False Positive)~~"
                st.markdown(title)
                st.caption(
                    f"{gap_label} | {gap['severity'].upper()} | "
                    f"`{gap.get('file_path', '')}:{gap.get('line', '')}`"
                )
                if gap.get("divergence_description"):
                    st.markdown(f"_{gap['divergence_description']}_")
                if gap.get("recommendation"):
                    st.info(gap["recommendation"])

            with col2:
                if gap.get("similarity_score"):
                    st.metric("Score", f"{gap['similarity_score']:.2f}")

            with col3:
                label = "Aufheben" if fp else "False Positive"
                if st.button(label, key=f"fp_{gap['id']}"):
                    try:
                        client.update_false_positive(gap["id"], not fp)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fehler: {e}")

    # Export
    st.divider()
    st.subheader("Export")
    col1, col2 = st.columns(2)
    with col1:
        json_data = json.dumps(report, indent=2, ensure_ascii=False)
        st.download_button(
            "JSON herunterladen",
            data=json_data,
            file_name=f"gap_report_{report['id']}.json",
            mime="application/json",
        )
    with col2:
        # Build CSV
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["gap_type", "severity", "code_element", "file_path", "line", "description"])
        for g in gaps:
            writer.writerow([
                g["gap_type"], g["severity"], g.get("code_element_name", ""),
                g.get("file_path", ""), g.get("line", ""), g.get("divergence_description", ""),
            ])
        st.download_button(
            "CSV herunterladen",
            data=output.getvalue(),
            file_name=f"gap_report_{report['id']}.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
