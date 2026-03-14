"""Gap table display component."""

import streamlit as st

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


def render_gap_table(gaps: list[dict], on_toggle_fp=None):
    """Render a filterable table of gap items."""
    for gap in gaps:
        sev_icon = SEVERITY_BADGES.get(gap["severity"], "⚪")
        gap_label = GAP_TYPE_LABELS.get(gap["gap_type"], gap["gap_type"])
        fp = gap.get("is_false_positive", False)

        with st.container(border=True):
            col1, col2 = st.columns([5, 1])

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

            with col2:
                if on_toggle_fp:
                    label = "Aufheben" if fp else "FP"
                    if st.button(label, key=f"fp_{gap['id']}"):
                        on_toggle_fp(gap["id"], not fp)
