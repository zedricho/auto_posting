"""Event Order Reconciliation Tool — Streamlit App."""

import os
import tempfile
from datetime import datetime

import pandas as pd
import streamlit as st

from recon.parser import parse_pdf_multiday
from recon.builder import compute_totals, generate_excel
from recon.delphi_adapter import parse_delphi_report
from recon.reconciler import reconcile
from recon.workflow import (
    load_workflow, save_workflow, get_default_workflow,
    WorkflowNode, WorkflowData, TEAM_COLORS, TEAM_COLORS_DARK, TEAM_LABELS,
)
from recon.packing import (
    generate_packing_list, get_items_by_category, save_packing_list,
    CATEGORY_LABELS, CATEGORY_ORDER, PackingList,
)


def check_password() -> bool:
    """Simple password authentication."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if password == st.secrets.get("password", ""):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False


def main():
    st.set_page_config(
        page_title="EO Reconciliation Tool",
        page_icon="📊",
        layout="wide",
    )

    # Authentication
    if not check_password():
        st.stop()

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["Overview", "Packing Lists", "Reconciliation"],
        label_visibility="collapsed",
    )

    if page == "Overview":
        render_overview()
    elif page == "Packing Lists":
        render_packing()
    else:
        render_reconciliation()


def render_reconciliation():
    """Main reconciliation wizard (4-step flow)."""
    st.title("📊 Event Order Reconciliation Tool")

    # Initialize session state
    if "step" not in st.session_state:
        st.session_state.step = 1
    if "event_order" not in st.session_state:
        st.session_state.event_order = None
    if "worksheet_output" not in st.session_state:
        st.session_state.worksheet_output = None

    # Progress indicator
    steps = ["1. Upload & Extract", "2. Complete Values", "3. Generate Worksheet", "4. Reconcile"]
    cols = st.columns(4)
    for i, (col, step_name) in enumerate(zip(cols, steps), 1):
        if i < st.session_state.step:
            col.success(step_name)
        elif i == st.session_state.step:
            col.info(step_name)
        else:
            col.empty()
            col.write(step_name)

    st.divider()

    # Render current step
    if st.session_state.step == 1:
        render_step_1_upload()
    elif st.session_state.step == 2:
        render_step_2_values()
    elif st.session_state.step == 3:
        render_step_3_generate()
    elif st.session_state.step == 4:
        render_step_4_reconcile()


def render_overview():
    """Operations workflow overview page - connected flowchart with inline note popups."""
    st.title("🏢 Operations Overview")

    # Load workflow data
    if "workflow_data" not in st.session_state:
        st.session_state.workflow_data = load_workflow()
    if "expanded_node" not in st.session_state:
        st.session_state.expanded_node = None

    workflow = st.session_state.workflow_data

    # Custom CSS for connected flowchart
    st.markdown("""
    <style>
    .flowchart {
        background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%);
        border-radius: 16px;
        padding: 25px;
        margin: 10px 0;
    }
    .flow-row {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 8px;
        margin: 8px 0;
        flex-wrap: wrap;
    }
    .flow-node {
        padding: 10px 16px;
        border-radius: 8px;
        text-align: center;
        font-weight: 600;
        font-size: 13px;
        border: 2px solid #444;
        cursor: pointer;
        transition: all 0.2s ease;
        min-width: 85px;
        box-shadow: 2px 2px 6px rgba(0,0,0,0.15);
    }
    .flow-node:hover {
        transform: translateY(-2px);
        box-shadow: 3px 4px 10px rgba(0,0,0,0.25);
    }
    .flow-node-key {
        border-width: 3px;
        font-size: 15px;
        padding: 12px 20px;
        font-weight: 700;
    }
    .flow-arrow {
        color: #555;
        font-size: 18px;
        font-weight: bold;
    }
    .flow-arrow-down {
        text-align: center;
        color: #555;
        font-size: 18px;
        margin: 4px 0;
    }
    .note-badge {
        font-size: 10px;
        background: rgba(0,0,0,0.15);
        border-radius: 8px;
        padding: 1px 5px;
        margin-left: 4px;
    }
    .node-popup {
        background: white;
        border: 2px solid #333;
        border-radius: 12px;
        padding: 15px;
        margin: 10px 0;
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
    }
    .section-title {
        font-size: 14px;
        font-weight: 600;
        color: #444;
        margin-bottom: 12px;
        padding-bottom: 6px;
        border-bottom: 2px solid #ddd;
    }
    </style>
    """, unsafe_allow_html=True)

    # Legend
    st.markdown("##### Team Colors")
    legend_html = '<div style="display:flex; gap:15px; flex-wrap:wrap; margin-bottom:15px;">'
    for team, color in TEAM_COLORS.items():
        dark = TEAM_COLORS_DARK[team]
        legend_html += f'''<div style="background: linear-gradient(135deg, {dark}, {color});
            padding: 6px 14px; border-radius: 6px; font-weight: 600; font-size: 12px;
            border: 2px solid #333;">{TEAM_LABELS[team]}</div>'''
    legend_html += '</div>'
    st.markdown(legend_html, unsafe_allow_html=True)

    # Helper functions
    def get_color(node):
        colors = TEAM_COLORS_DARK if node.is_key_member else TEAM_COLORS
        return colors.get(node.team, "#D3D3D3")

    def node_html(node_id):
        """Generate HTML for a node."""
        node = workflow.get_node(node_id)
        if not node:
            return ""
        color = get_color(node)
        key_class = " flow-node-key" if node.is_key_member else ""
        badge = f'<span class="note-badge">📝{len(node.notes)}</span>' if node.notes else ""
        return f'<div class="flow-node{key_class}" style="background:{color};">{node.label}{badge}</div>'

    def render_node_with_popup(node_id, container=None):
        """Render a clickable node that expands to show notes inline."""
        node = workflow.get_node(node_id)
        if not node:
            return

        ctx = container if container else st
        color = get_color(node)
        is_expanded = st.session_state.expanded_node == node_id
        notes_badge = f" 📝{len(node.notes)}" if node.notes else ""

        # Node button with team color
        btn_style = "primary" if node.is_key_member else "secondary"
        if ctx.button(
            f"{node.label}{notes_badge}",
            key=f"node_{node_id}",
            type=btn_style,
        ):
            # Toggle expansion - clicking same node closes it, clicking different opens new
            if st.session_state.expanded_node == node_id:
                st.session_state.expanded_node = None
            else:
                st.session_state.expanded_node = node_id
            st.rerun()

        # Show popup if this node is expanded
        if is_expanded:
            with ctx.container():
                st.markdown(
                    f'''<div class="node-popup">
                    <div style="background:{color}; padding:10px; border-radius:8px; margin-bottom:10px;">
                        <strong>{node.label}</strong> — {TEAM_LABELS.get(node.team, node.team)}<br>
                        <span style="font-size:12px; color:#333;">{node.description}</span>
                    </div>
                    </div>''',
                    unsafe_allow_html=True
                )

                # Notes section
                if node.notes:
                    for i, note in enumerate(node.notes):
                        nc1, nc2 = st.columns([6, 1])
                        nc1.markdown(f"• {note}")
                        if nc2.button("🗑️", key=f"del_{node_id}_{i}"):
                            node.notes.pop(i)
                            save_workflow(workflow)
                            st.rerun()

                # Add note input
                new_note = st.text_input("Add note:", key=f"note_input_{node_id}", placeholder="Type and press Enter...")
                col1, col2 = st.columns(2)
                if col1.button("💾 Save", key=f"save_{node_id}"):
                    if new_note.strip():
                        workflow.add_note(node_id, new_note.strip())
                        save_workflow(workflow)
                        st.rerun()
                if col2.button("✖️ Close", key=f"close_{node_id}"):
                    st.session_state.expanded_node = None
                    st.rerun()

    # ========== MAIN FLOWCHART ==========

    # --- PLANNING & OPERATIONS (side by side) ---
    st.markdown("### 📋 Planning → Operations Flow")

    plan_col, mid_col, ops_col = st.columns([1, 0.15, 1])

    with plan_col:
        st.markdown('<div class="flowchart">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">📌 Planning</div>', unsafe_allow_html=True)

        # Sales → Initial Event
        c1, c2, c3 = st.columns([1, 0.2, 1])
        render_node_with_popup("sales", c1)
        c2.markdown('<p class="flow-arrow" style="text-align:center;">→</p>', unsafe_allow_html=True)
        render_node_with_popup("initial_event", c3)

        st.markdown('<p class="flow-arrow-down">↓</p>', unsafe_allow_html=True)

        # Delphi ↔ Daily Updates
        c1, c2, c3 = st.columns([1, 0.2, 1])
        render_node_with_popup("delphi", c1)
        c2.markdown('<p class="flow-arrow" style="text-align:center;">↔</p>', unsafe_allow_html=True)
        render_node_with_popup("daily_updates", c3)

        st.markdown('<p class="flow-arrow-down">↓</p>', unsafe_allow_html=True)

        # Planners (KEY)
        render_node_with_popup("planners")

        st.markdown('<p class="flow-arrow-down">↓</p>', unsafe_allow_html=True)

        # Export EO
        render_node_with_popup("export_eo")

        st.markdown('</div>', unsafe_allow_html=True)

    with mid_col:
        st.markdown('<p style="text-align:center; font-size:28px; margin-top:120px; color:#555;">→</p>', unsafe_allow_html=True)

    with ops_col:
        st.markdown('<div class="flowchart">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">⚙️ Operations</div>', unsafe_allow_html=True)

        # Rapid/Go
        render_node_with_popup("rapid_go")

        st.markdown('<p class="flow-arrow-down">↓</p>', unsafe_allow_html=True)

        # Log Team + branches
        c1, c2, c3 = st.columns(3)
        render_node_with_popup("log_team", c1)
        render_node_with_popup("linen_orders", c2)
        render_node_with_popup("mobile_doc", c3)

        st.markdown('<p class="flow-arrow-down">↓</p>', unsafe_allow_html=True)

        # Outputs
        c1, c2, c3 = st.columns(3)
        render_node_with_popup("packing_sheets", c1)
        render_node_with_popup("room_flips", c2)
        render_node_with_popup("asset_movement", c3)

        st.markdown('</div>', unsafe_allow_html=True)

    # --- MANAGEMENT ---
    st.markdown("### 👔 Management & Rostering")

    st.markdown('<div class="flowchart">', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns([1, 0.15, 1, 0.15])
    render_node_with_popup("management", c1)
    c2.markdown('<p class="flow-arrow" style="text-align:center;">→</p>', unsafe_allow_html=True)
    render_node_with_popup("roster_build", c3)
    c4.markdown('<p style="color:#666; font-size:11px;">(Labour %)</p>', unsafe_allow_html=True)

    st.markdown('<p class="flow-arrow-down">↓</p>', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns([1, 0.15, 1, 1])
    render_node_with_popup("plan_wtc", c1)
    c2.markdown('<p class="flow-arrow" style="text-align:center;">→</p>', unsafe_allow_html=True)
    render_node_with_popup("poa", c3)

    st.markdown('</div>', unsafe_allow_html=True)

    # --- FLOOR MANAGERS & DELIVERY ---
    st.markdown("### 🎯 Floor Managers & Event Delivery")

    fm_col, delivery_col = st.columns([1.3, 1])

    with fm_col:
        st.markdown('<div class="flowchart">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">🔵 FM Operations</div>', unsafe_allow_html=True)

        c1, c2, c3 = st.columns([1, 0.15, 1])
        render_node_with_popup("cross_checks", c1)
        c2.markdown('<p class="flow-arrow" style="text-align:center;">→</p>', unsafe_allow_html=True)
        render_node_with_popup("postings", c3)

        st.markdown('<p class="flow-arrow-down">↓</p>', unsafe_allow_html=True)

        c1, c2, c3 = st.columns([1, 0.15, 1])
        render_node_with_popup("fm", c1)
        c2.markdown('<p class="flow-arrow" style="text-align:center;">↔</p>', unsafe_allow_html=True)
        render_node_with_popup("opera", c3)

        st.markdown('<p class="flow-arrow-down">↓</p>', unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        render_node_with_popup("buildbooks", c1)
        render_node_with_popup("fix_pay", c2)
        render_node_with_popup("roster_issues", c3)
        render_node_with_popup("function_report", c4)

        st.markdown('</div>', unsafe_allow_html=True)

    with delivery_col:
        st.markdown('<div class="flowchart">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">🎪 Event Delivery</div>', unsafe_allow_html=True)

        render_node_with_popup("captains")

        st.markdown('<p class="flow-arrow-down">↓</p>', unsafe_allow_html=True)

        render_node_with_popup("floor_management")

        st.markdown('''
        <div style="margin-top:12px; color:#555; font-size:12px; padding:8px;
            background:rgba(255,255,255,0.7); border-radius:6px;">
            • Break allocations<br>• Set rooms & bars<br>• Staff coordination
        </div>
        ''', unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    # --- ADD NEW NODE & FOOTER ---
    st.divider()

    with st.expander("➕ Add New Node"):
        c1, c2, c3 = st.columns(3)
        with c1:
            new_id = st.text_input("Node ID", key="new_node_id")
            new_label = st.text_input("Label", key="new_node_label")
        with c2:
            new_team = st.selectbox("Team", list(TEAM_COLORS.keys()),
                format_func=lambda x: TEAM_LABELS.get(x, x), key="new_node_team")
            new_key = st.checkbox("Key member", key="new_node_key")
        with c3:
            new_desc = st.text_area("Description", key="new_node_desc", height=80)

        if st.button("Create Node"):
            if new_id and new_label:
                if workflow.get_node(new_id):
                    st.error("ID exists")
                else:
                    workflow.add_node(WorkflowNode(
                        id=new_id, label=new_label, team=new_team,
                        description=new_desc, is_key_member=new_key
                    ))
                    save_workflow(workflow)
                    st.success(f"Created '{new_label}'")
                    st.rerun()

    # Footer
    fc1, fc2 = st.columns([4, 1])
    fc1.caption(f"Last updated: {workflow.last_updated[:19] if workflow.last_updated else 'Never'}")
    if fc2.button("🔄 Reset"):
        st.session_state.workflow_data = get_default_workflow()
        save_workflow(st.session_state.workflow_data)
        st.session_state.expanded_node = None
        st.rerun()


def render_packing():
    """Packing list generator page."""
    st.title("📦 Packing List Generator")

    # Initialize session state
    if "packing_list" not in st.session_state:
        st.session_state.packing_list = None
    if "packing_eo_pax" not in st.session_state:
        st.session_state.packing_eo_pax = None
    if "packing_eo_tables" not in st.session_state:
        st.session_state.packing_eo_tables = None

    # ============ STEP 1: EO UPLOAD (OPTIONAL) ============
    st.markdown("### Step 1: Load from Event Order (Optional)")

    with st.expander("📄 Upload EO to auto-fill details", expanded=False):
        eo_file = st.file_uploader("Upload EO PDF", type=["pdf"], key="packing_eo_upload")

        if eo_file is not None:
            if st.button("Extract from EO"):
                with st.spinner("Reading EO..."):
                    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                        tmp.write(eo_file.read())
                        tmp_path = tmp.name

                    try:
                        event_days = parse_pdf_multiday(tmp_path)
                        if event_days:
                            # Use first day with most line items
                            best_day = max(event_days, key=lambda d: len(d.event_order.line_items))
                            eo = best_day.event_order

                            # Extract pax from day delegate package or max GTD
                            pax_estimate = 0
                            for item in eo.line_items:
                                if item.pax and item.pax > pax_estimate:
                                    pax_estimate = item.pax

                            # Estimate tables (assume 10 pax per table)
                            tables_estimate = max(1, pax_estimate // 10) if pax_estimate else 0

                            st.session_state.packing_eo_pax = pax_estimate
                            st.session_state.packing_eo_tables = tables_estimate
                            st.session_state.packing_event_name = eo.event_name or ""
                            st.session_state.packing_event_date = eo.event_date

                            st.success(f"Extracted: {eo.event_name} - {pax_estimate} pax suggested")
                    except Exception as e:
                        st.error(f"Error reading EO: {e}")
                    finally:
                        os.unlink(tmp_path)

        if st.session_state.packing_eo_pax:
            st.info(f"**EO Suggestion:** {st.session_state.packing_eo_pax} pax, ~{st.session_state.packing_eo_tables} tables")

    st.divider()

    # ============ STEP 2: EVENT CONFIGURATION ============
    st.markdown("### Step 2: Event Configuration")

    col1, col2 = st.columns(2)

    with col1:
        event_name = st.text_input(
            "Event Name",
            value=st.session_state.get("packing_event_name", ""),
            key="packing_name_input"
        )
        event_date = st.date_input(
            "Event Date",
            value=st.session_state.get("packing_event_date", datetime.now().date()),
            key="packing_date_input"
        )
        location = st.selectbox(
            "Location",
            ["Brisbane Ballroom", "Event Centre", "Level 7", "Other"],
            key="packing_location"
        )

    with col2:
        # Use EO suggestions as defaults if available
        default_pax = st.session_state.packing_eo_pax or 100
        default_tables = st.session_state.packing_eo_tables or 10

        pax = st.number_input(
            "Guest Count (Pax)",
            min_value=1, max_value=2000,
            value=default_pax,
            step=10,
            key="packing_pax"
        )
        tables = st.number_input(
            "Table Count",
            min_value=1, max_value=200,
            value=default_tables,
            step=1,
            key="packing_tables"
        )

        # Show if overriding EO suggestion
        if st.session_state.packing_eo_pax and pax != st.session_state.packing_eo_pax:
            st.caption(f"EO suggested: {st.session_state.packing_eo_pax} pax")

    st.divider()

    # ============ STEP 3: SERVICE OPTIONS ============
    st.markdown("### Step 3: Service Options")

    opt_col1, opt_col2, opt_col3 = st.columns(3)

    with opt_col1:
        courses = st.radio(
            "Courses",
            [1, 2, 3],
            index=1,  # Default to 2 courses
            horizontal=True,
            key="packing_courses"
        )
        has_tc = st.checkbox("Preset Tea & Coffee", key="packing_tc")
        has_canapes = st.checkbox("Canapés", key="packing_canapes")
        has_foh_bar = st.checkbox("FOH Bar Required", key="packing_foh")

    with opt_col2:
        st.markdown("**Linen Colours**")
        napkin_color = st.radio(
            "Napkins",
            ["black", "white"],
            horizontal=True,
            format_func=lambda x: x.title(),
            key="packing_napkin_color"
        )
        underliner_color = st.radio(
            "Underliners",
            ["black", "white"],
            horizontal=True,
            format_func=lambda x: x.title(),
            key="packing_underliner_color"
        )

    with opt_col3:
        st.markdown("&nbsp;")  # Spacer to align with col2
        round_color = st.radio(
            "Rounds (Tablecloths)",
            ["black", "white"],
            horizontal=True,
            format_func=lambda x: x.title(),
            key="packing_round_color"
        )

    st.divider()

    # ============ GENERATE BUTTON ============
    if st.button("📋 Generate Packing List", type="primary", use_container_width=True):
        packing_list = generate_packing_list(
            event_name=event_name,
            event_date=event_date,
            location=location,
            pax=pax,
            tables=tables,
            courses=courses,
            has_tc=has_tc,
            has_foh_bar=has_foh_bar,
            has_canapes=has_canapes,
            napkin_color=napkin_color,
            underliner_color=underliner_color,
            round_color=round_color,
        )
        st.session_state.packing_list = packing_list
        st.rerun()

    # ============ STEP 4: REVIEW & EDIT ITEMS ============
    if st.session_state.packing_list:
        packing_list = st.session_state.packing_list

        st.markdown("### Step 4: Review & Adjust Items")

        # Event summary
        st.markdown(f"""
        **{packing_list.event_name}** | {packing_list.event_date} | {packing_list.location}
        **{packing_list.pax} pax** | **{packing_list.tables} tables** | {packing_list.courses} course | Napkins: {packing_list.napkin_color.title()}, Underliners: {packing_list.underliner_color.title()}, Rounds: {packing_list.round_color.title()}
        """)

        st.divider()

        # Items by category
        items_by_cat = get_items_by_category(packing_list)

        for category in CATEGORY_ORDER:
            items = items_by_cat.get(category, [])
            # Only show categories with items that have qty > 0 or are always shown
            active_items = [i for i in items if i.final_qty > 0]

            if not active_items and category in ["bar_foh", "tc", "canape"]:
                continue  # Skip empty optional categories

            with st.expander(f"**{CATEGORY_LABELS[category]}** ({len(active_items)} items)", expanded=True):
                if not items:
                    st.caption("No items in this category")
                    continue

                # Create editable table
                for i, item in enumerate(items):
                    if item.final_qty == 0 and category in ["linen"]:
                        # Skip zero-qty linen (wrong color)
                        continue

                    col1, col2, col3, col4 = st.columns([3, 1, 1, 2])

                    with col1:
                        st.markdown(f"**{item.name}**")

                    with col2:
                        st.caption(f"Suggested: {item.suggested_qty}")

                    with col3:
                        # Editable quantity
                        new_qty = st.number_input(
                            "Qty",
                            min_value=0,
                            value=item.final_qty,
                            step=1,
                            key=f"qty_{category}_{i}",
                            label_visibility="collapsed"
                        )
                        # Update if changed
                        if new_qty != item.final_qty:
                            item.final_qty = new_qty

                    with col4:
                        if item.notes:
                            st.caption(item.notes)

        st.divider()

        # ============ STEP 5: EXPORT ============
        st.markdown("### Step 5: Export")

        export_col1, export_col2, export_col3 = st.columns(3)

        with export_col1:
            if st.button("📊 Download Excel", use_container_width=True):
                # Generate Excel file matching current format
                excel_bytes = generate_packing_excel(packing_list)
                st.download_button(
                    label="📥 Save Excel File",
                    data=excel_bytes,
                    file_name=f"packing_{packing_list.event_name.replace(' ', '_')}_{packing_list.id}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="download_packing_excel"
                )

        with export_col2:
            if st.button("💾 Save Draft", use_container_width=True):
                save_packing_list(packing_list)
                st.success("Draft saved!")

        with export_col3:
            if st.button("🔄 Clear & Start Over", use_container_width=True):
                st.session_state.packing_list = None
                st.session_state.packing_eo_pax = None
                st.session_state.packing_eo_tables = None
                st.rerun()


def generate_packing_excel(packing_list: PackingList) -> bytes:
    """Generate Excel file matching the current packing sheet format."""
    from io import BytesIO
    import xlsxwriter

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    worksheet = workbook.add_worksheet("Packing List")

    # Formats
    header_fmt = workbook.add_format({"bold": True, "font_size": 12})
    section_fmt = workbook.add_format({"bold": True, "bg_color": "#D9D9D9", "border": 1})
    cell_fmt = workbook.add_format({"border": 1})
    qty_fmt = workbook.add_format({"border": 1, "align": "center"})

    # Column widths
    worksheet.set_column(0, 0, 30)  # Item name
    worksheet.set_column(1, 1, 12)  # Quantity
    worksheet.set_column(2, 2, 12)  # Packed Y/N
    worksheet.set_column(3, 3, 30)  # Notes

    row = 0

    # Header section
    worksheet.write(row, 0, "EVENT NAME:", header_fmt)
    worksheet.write(row, 3, packing_list.event_name)
    row += 1

    worksheet.write(row, 0, "EVENT DATE:", header_fmt)
    worksheet.write(row, 3, str(packing_list.event_date) if packing_list.event_date else "")
    row += 1

    worksheet.write(row, 0, "GUEST COUNT:", header_fmt)
    worksheet.write(row, 1, packing_list.pax)
    row += 1

    worksheet.write(row, 0, "TABLE COUNT:", header_fmt)
    worksheet.write(row, 1, packing_list.tables)
    row += 1

    worksheet.write(row, 0, "EVENT LOCATION:", header_fmt)
    worksheet.write(row, 3, packing_list.location)
    row += 1

    row += 1  # Empty row

    # Items by category
    items_by_cat = get_items_by_category(packing_list)

    for category in CATEGORY_ORDER:
        items = items_by_cat.get(category, [])
        active_items = [i for i in items if i.final_qty > 0]

        if not active_items:
            continue

        # Category header
        worksheet.write(row, 0, CATEGORY_LABELS[category], section_fmt)
        worksheet.write(row, 1, "QUANTITY", section_fmt)
        worksheet.write(row, 2, "PACKED (Y/N)", section_fmt)
        worksheet.write(row, 3, "NOTES", section_fmt)
        row += 1

        # Items
        for item in active_items:
            worksheet.write(row, 0, item.name, cell_fmt)
            worksheet.write(row, 1, item.final_qty, qty_fmt)
            worksheet.write(row, 2, "", cell_fmt)  # Packed column (empty for manual check)
            worksheet.write(row, 3, item.notes, cell_fmt)
            row += 1

        row += 1  # Empty row between sections

    # Sign-off section
    row += 1
    worksheet.write(row, 0, "Packers/Captains Sign off", header_fmt)
    row += 1
    worksheet.write(row, 0, "Name:")
    row += 1
    worksheet.write(row, 0, "Signature:")

    workbook.close()
    output.seek(0)
    return output.getvalue()


def render_step_1_upload():
    """Step 1: Upload EO PDF and extract data."""
    st.header("Step 1: Upload & Extract")
    st.write("Upload an Event Order PDF to extract line items.")

    # Initialize multi-day session state
    if "event_days" not in st.session_state:
        st.session_state.event_days = None
    if "selected_day_idx" not in st.session_state:
        st.session_state.selected_day_idx = 0

    uploaded_file = st.file_uploader("Choose an EO PDF", type=["pdf"])

    if uploaded_file is not None:
        if st.button("Extract"):
            with st.spinner("Extracting..."):
                # Save to temp file for pdfplumber
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(uploaded_file.read())
                    tmp_path = tmp.name

                try:
                    event_days = parse_pdf_multiday(tmp_path)
                    st.session_state.event_days = event_days
                    st.session_state.selected_day_idx = 0

                    if len(event_days) > 1:
                        st.success(f"Multi-day event detected: {len(event_days)} days found")
                    else:
                        st.session_state.event_order = event_days[0].event_order
                        st.success(f"Extracted {len(event_days[0].event_order.line_items)} line items")
                except Exception as e:
                    st.error(f"Error extracting PDF: {e}")
                    return
                finally:
                    os.unlink(tmp_path)

    # Multi-day event: show day selector
    if st.session_state.event_days is not None and len(st.session_state.event_days) > 1:
        st.divider()
        st.subheader("📅 Multi-Day Event")
        st.info("This event spans multiple days. Select which day to process for posting.")

        event_days = st.session_state.event_days

        # Create day selection options
        day_options = []
        for day in event_days:
            date_str = day.event_order.event_date.strftime("%a %d %b %Y") if day.event_order.event_date else "Unknown date"
            items_count = len(day.event_order.line_items)
            day_options.append(f"Day {day.day_number}: {date_str} (BEO# {day.event_order.beo_number}) - {items_count} items")

        selected_idx = st.radio(
            "Select day to process:",
            range(len(day_options)),
            format_func=lambda i: day_options[i],
            index=st.session_state.selected_day_idx,
            key="day_selector",
        )

        if selected_idx != st.session_state.selected_day_idx:
            st.session_state.selected_day_idx = selected_idx

        # Set the selected day's event order
        st.session_state.event_order = event_days[selected_idx].event_order

    # Show extracted data if available
    if st.session_state.event_order is not None:
        event = st.session_state.event_order
        st.divider()
        st.subheader("Event Details")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("PM#", event.pm_number or "—")
        col2.metric("BEO#", event.beo_number or "—")
        col3.metric("Event", event.event_name or "—")
        if event.event_date:
            col4.metric("Date", event.event_date.strftime("%d %b %Y"))
        else:
            col4.metric("Date", "—")

        st.subheader("Line Items")

        # Convert to dataframe for editing
        items_data = []
        for i, item in enumerate(event.line_items):
            items_data.append({
                "idx": i,
                "Category": item.category,
                "Type": item.type,
                "Basis": item.basis,
                "Qty/Pax": item.pax or item.qty or item.guards or "",
                "Unit Price": item.unit_price or "",
                "Value": item.value,
                "Money Type": item.money_type,
                "Needs Value": "⚠️" if item.needs_manual_value else "✓",
            })

        df = pd.DataFrame(items_data)

        # Highlight rows needing manual values
        st.dataframe(
            df.drop(columns=["idx"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
        )

        # Count items needing values
        needs_values = sum(1 for item in event.line_items if item.needs_manual_value)
        if needs_values > 0:
            st.warning(f"{needs_values} line(s) need manual values (consumption/cash)")

        if st.button("Confirm Extraction →"):
            st.session_state.step = 2
            st.rerun()


def render_step_2_values():
    """Step 2: Enter consumption/cash values."""
    st.header("Step 2: Complete Values")

    if st.session_state.event_order is None:
        st.error("No event order loaded. Go back to Step 1.")
        if st.button("← Back to Step 1"):
            st.session_state.step = 1
            st.rerun()
        return

    event = st.session_state.event_order

    # Find items needing manual values
    needs_values = [
        (i, item) for i, item in enumerate(event.line_items)
        if item.needs_manual_value
    ]

    if not needs_values:
        st.success("All line items have values. Proceeding to next step.")
        st.session_state.step = 3
        st.rerun()
        return

    st.write(f"Enter values for {len(needs_values)} line(s):")

    # Create input fields for each item needing a value
    updated = False
    for idx, item in needs_values:
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.write(f"**{item.type}**")
            st.caption(f"Category: {item.category} | Type: {item.money_type}")
        with col2:
            source = "POS" if item.money_type == "cash" else "Post-event"
            st.caption(f"Source: {source}")
        with col3:
            # If we know the unit price, ask for quantity instead of total value
            if item.unit_price and item.unit_price > 0:
                # Determine what quantity to ask for based on basis
                if item.basis == "hourly":
                    qty_label = "Total hours"
                    qty_step = 0.5
                else:
                    qty_label = "Quantity"
                    qty_step = 1.0

                st.caption(f"@ ${item.unit_price:,.2f} each")
                qty = st.number_input(
                    qty_label,
                    min_value=0.0,
                    value=0.0,
                    step=qty_step,
                    key=f"qty_{idx}",
                    format="%.1f" if item.basis == "hourly" else "%.0f",
                )
                new_value = round(qty * item.unit_price, 2)
                if new_value != item.value:
                    event.line_items[idx].value = new_value
                    if item.basis == "hourly":
                        event.line_items[idx].hours = qty
                    else:
                        event.line_items[idx].qty = int(qty) if qty > 0 else None
                    updated = True
                st.caption(f"= ${new_value:,.2f}")
            else:
                # No unit price known - ask for total value directly
                new_value = st.number_input(
                    "Value ($)",
                    min_value=0.0,
                    value=item.value,
                    step=0.01,
                    key=f"value_{idx}",
                    format="%.2f",
                )
                if new_value != item.value:
                    event.line_items[idx].value = new_value
                    updated = True

    if updated:
        st.session_state.event_order = event

    # Show running totals
    st.divider()
    st.subheader("Running Totals")

    from recon.builder import compute_totals
    preview = compute_totals(event)

    col1, col2 = st.columns(2)
    col1.metric("Delphi Total", f"${preview.delphi_grand_total:,.2f}")
    col2.metric("Opera Total", f"${preview.opera_grand_total:,.2f}")

    st.divider()

    # Navigation
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back"):
            st.session_state.step = 1
            st.rerun()
    with col2:
        # Allow proceeding - $0 is valid for consumption that didn't happen
        if st.button("Values Complete →"):
            st.session_state.step = 3
            st.rerun()


def render_step_3_generate():
    """Step 3: Generate worksheet and download."""
    st.header("Step 3: Generate Worksheet")

    if st.session_state.event_order is None:
        st.error("No event order loaded. Go back to Step 1.")
        if st.button("← Back to Step 1"):
            st.session_state.step = 1
            st.rerun()
        return

    event = st.session_state.event_order

    # Compute totals
    from recon.builder import compute_totals, generate_excel

    worksheet_output = compute_totals(event)
    st.session_state.worksheet_output = worksheet_output

    # Event info
    st.subheader("Event")
    st.write(f"**{event.event_name}** | PM# {event.pm_number} | BEO# {event.beo_number}")
    if event.event_date:
        st.write(f"Date: {event.event_date}")

    # Category totals table
    st.subheader("Category Totals")

    totals_data = []
    for total in worksheet_output.totals:
        totals_data.append({
            "Category": total.category.replace("_", " ").title(),
            "Delphi (incl cash)": f"${total.delphi_total:,.2f}",
            "Opera (excl cash)": f"${total.opera_total:,.2f}",
        })

    totals_data.append({
        "Category": "**TOTAL**",
        "Delphi (incl cash)": f"**${worksheet_output.delphi_grand_total:,.2f}**",
        "Opera (excl cash)": f"**${worksheet_output.opera_grand_total:,.2f}**",
    })

    st.table(pd.DataFrame(totals_data))

    # Grand totals prominently
    col1, col2 = st.columns(2)
    col1.metric("Delphi Grand Total", f"${worksheet_output.delphi_grand_total:,.2f}")
    col2.metric("Opera Grand Total", f"${worksheet_output.opera_grand_total:,.2f}")

    # Download button
    st.divider()
    excel_bytes = generate_excel(worksheet_output)

    filename = f"worksheet_{event.beo_number or 'export'}.xlsx"
    st.download_button(
        label="📥 Download Worksheet (.xlsx)",
        data=excel_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.divider()

    # Navigation
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("← Back"):
            st.session_state.step = 2
            st.rerun()
    with col2:
        if st.button("Proceed to Reconciliation →"):
            st.session_state.step = 4
            st.rerun()
    with col3:
        if st.button("✓ Done (Skip Reconciliation)"):
            st.balloons()
            st.success("Worksheet generated successfully!")


def render_step_4_reconcile():
    """Step 4: Upload Delphi report and reconcile."""
    st.header("Step 4: Reconcile")

    if st.session_state.worksheet_output is None:
        st.error("No worksheet generated. Go back to Step 3.")
        if st.button("← Back to Step 3"):
            st.session_state.step = 3
            st.rerun()
        return

    worksheet = st.session_state.worksheet_output

    st.write("Upload the Delphi posting report to compare against computed totals.")

    uploaded_file = st.file_uploader("Choose Delphi Report (.xlsx)", type=["xlsx"])

    if uploaded_file is not None:
        if st.button("Reconcile"):
            with st.spinner("Reconciling..."):
                from io import BytesIO
                from recon.delphi_adapter import parse_delphi_report
                from recon.reconciler import reconcile

                try:
                    delphi_report = parse_delphi_report(BytesIO(uploaded_file.read()))
                    discrepancies = reconcile(worksheet, delphi_report)
                    st.session_state.discrepancies = discrepancies
                    st.session_state.delphi_report = delphi_report
                except Exception as e:
                    st.error(f"Error parsing Delphi report: {e}")
                    return

    # Show results if available
    if "discrepancies" in st.session_state:
        discrepancies = st.session_state.discrepancies
        delphi_report = st.session_state.delphi_report

        st.divider()
        st.subheader("Reconciliation Results")

        if not discrepancies:
            st.success("✅ All categories match within tolerance!")
        else:
            st.warning(f"⚠️ {len(discrepancies)} discrepancy/ies found")

        # Build comparison table
        comparison_data = []
        for total in worksheet.totals:
            posted = delphi_report.get(total.category, 0.0)
            variance = posted - total.delphi_total

            # Determine status
            if abs(variance) <= 0.05:
                status = "✅ Match"
                cause = "—"
            else:
                status = "❌ Variance"
                disc = next((d for d in discrepancies if d.category == total.category), None)
                cause = disc.likely_cause if disc else "Unknown"

            comparison_data.append({
                "Category": total.category.replace("_", " ").title(),
                "Expected": f"${total.delphi_total:,.2f}",
                "Posted": f"${posted:,.2f}",
                "Variance": f"${variance:,.2f}",
                "Status": status,
                "Likely Cause": cause,
            })

        st.table(pd.DataFrame(comparison_data))

        # Discrepancy details
        if discrepancies:
            st.subheader("Discrepancy Details")
            for disc in discrepancies:
                with st.expander(f"🔴 {disc.category.replace('_', ' ').title()}: ${abs(disc.variance):,.2f} variance"):
                    st.write(f"**Expected:** ${disc.expected:,.2f}")
                    st.write(f"**Posted:** ${disc.posted:,.2f}")
                    st.write(f"**Variance:** ${disc.variance:,.2f}")
                    st.write(f"**Likely Cause:** {disc.likely_cause}")

    st.divider()

    # Navigation
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back"):
            st.session_state.step = 3
            st.rerun()
    with col2:
        if st.button("🔄 Start Over"):
            for key in list(st.session_state.keys()):
                if key != "authenticated":
                    del st.session_state[key]
            st.rerun()


if __name__ == "__main__":
    main()
