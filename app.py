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
    PackingList, EVENT_TYPES, BUFFET_SUB_TYPES, PLENARY_SUB_TYPES,
    get_category_order, get_category_labels, MULTI_MEAL_CONFIGS,
    BUFFET_CATEGORY_LABELS,
)
from recon.stocktake import (
    import_from_excel as import_stocktake_excel,
    import_base_from_excel,
    load_items as load_stocktake_items,
    save_items as save_stocktake_items,
    load_base_items, save_base_items, get_base_by_department,
    load_sessions, save_session, get_session,
    create_session, export_to_excel as export_stocktake_excel,
    get_items_by_department, get_items_by_category as get_stock_by_category,
    StockItem, StocktakeSession, StocktakeCount, BaseItem, DEPARTMENTS,
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
        ["Overview", "Packing Lists", "Stocktake", "Reconciliation"],
        label_visibility="collapsed",
    )

    if page == "Overview":
        render_overview()
    elif page == "Packing Lists":
        render_packing()
    elif page == "Stocktake":
        render_stocktake()
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

    # Event type selector
    event_type = st.selectbox(
        "Event Type",
        options=list(EVENT_TYPES.keys()),
        format_func=lambda x: EVENT_TYPES[x],
        key="packing_event_type"
    )

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

        # Tables for plated/buffet, trestles for plenary
        if event_type == "plenary":
            trestle_count = st.number_input(
                "Trestle Count",
                min_value=1, max_value=50,
                value=4,
                step=1,
                key="packing_trestles"
            )
            tables = default_tables  # Keep for compatibility
        else:
            tables = st.number_input(
                "Table Count",
                min_value=1, max_value=200,
                value=default_tables,
                step=1,
                key="packing_tables"
            )
            trestle_count = 0

        # Show if overriding EO suggestion
        if st.session_state.packing_eo_pax and pax != st.session_state.packing_eo_pax:
            st.caption(f"EO suggested: {st.session_state.packing_eo_pax} pax")

    st.divider()

    # ============ STEP 3: SERVICE OPTIONS ============
    st.markdown("### Step 3: Service Options")

    # Initialize default values for all event types
    courses = 2
    has_tc = False
    has_canapes = False
    has_foh_bar = False
    napkin_color = "black"
    underliner_color = "white"
    round_color = "black"
    sub_type = ""
    buffet_setups = 1
    hot_items = 0
    cold_items = 0
    tc_stations = 1
    water_stations = 1
    riser_color = "white"
    linen_style = "black_fitted"

    # === PLATED OPTIONS ===
    if event_type == "plated":
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

    # === BUFFET OPTIONS ===
    elif event_type == "buffet":
        # Sub-type selection
        sub_type = st.selectbox(
            "Buffet Type",
            options=list(BUFFET_SUB_TYPES.keys()),
            format_func=lambda x: BUFFET_SUB_TYPES[x],
            key="packing_buffet_subtype"
        )

        # Check if this is a multi-meal buffet
        is_multi_meal = sub_type in MULTI_MEAL_CONFIGS
        meal_sections_input = []

        if is_multi_meal:
            # Multi-meal buffet: show setup inputs for each meal section
            st.markdown("---")
            st.markdown("**Setup per Meal**")

            meal_configs = MULTI_MEAL_CONFIGS[sub_type]
            for i, meal_config in enumerate(meal_configs):
                section_id = meal_config["section_id"]
                section_name = meal_config["name"]

                with st.expander(f"**{section_name}**", expanded=True):
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        section_buffet_setups = st.number_input(
                            "Buffet Setups",
                            min_value=1, max_value=10,
                            value=1,
                            step=1,
                            key=f"packing_{section_id}_buffet_setups"
                        )
                    with col2:
                        section_hot_items = st.number_input(
                            "Hot Items",
                            min_value=0, max_value=20,
                            value=2 if section_id in ["lunch", "dinner", "breakfast"] else 0,
                            step=1,
                            key=f"packing_{section_id}_hot_items"
                        )
                    with col3:
                        section_cold_items = st.number_input(
                            "Cold Items",
                            min_value=0, max_value=20,
                            value=3,
                            step=1,
                            key=f"packing_{section_id}_cold_items"
                        )
                    with col4:
                        section_dessert_items = st.number_input(
                            "Dessert Items",
                            min_value=0, max_value=10,
                            value=2 if section_id in ["lunch", "dinner", "afternoon_tea"] else 0,
                            step=1,
                            key=f"packing_{section_id}_dessert_items"
                        )

                    meal_sections_input.append({
                        "section_id": section_id,
                        "name": section_name,
                        "buffet_setups": section_buffet_setups,
                        "hot_items": section_hot_items,
                        "cold_items": section_cold_items,
                        "dessert_items": section_dessert_items,
                    })

            st.markdown("---")
            st.markdown("**Shared Stations**")
            col1, col2, col3 = st.columns(3)
            with col1:
                tc_stations = st.number_input(
                    "Tea & Coffee Stations",
                    min_value=0, max_value=10,
                    value=1,
                    step=1,
                    key="packing_tc_stations"
                )
            with col2:
                water_stations = st.number_input(
                    "Water Stations",
                    min_value=0, max_value=10,
                    value=1,
                    step=1,
                    key="packing_water_stations"
                )
            with col3:
                riser_color = st.radio(
                    "Riser Sets",
                    ["white", "black"],
                    horizontal=True,
                    format_func=lambda x: x.title(),
                    key="packing_riser_color"
                )
            has_tc = tc_stations > 0

        else:
            # Single-meal buffet: original layout
            opt_col1, opt_col2, opt_col3 = st.columns(3)

            with opt_col1:
                st.markdown("**Buffet Setup**")
                buffet_setups = st.number_input(
                    "Number of Buffet Setups",
                    min_value=1, max_value=10,
                    value=1,
                    step=1,
                    key="packing_buffet_setups"
                )
                hot_items = st.number_input(
                    "Hot Items",
                    min_value=0, max_value=20,
                    value=3,
                    step=1,
                    key="packing_hot_items"
                )
                cold_items = st.number_input(
                    "Cold Items",
                    min_value=0, max_value=20,
                    value=2,
                    step=1,
                    key="packing_cold_items"
                )

            with opt_col2:
                st.markdown("**Stations**")
                tc_stations = st.number_input(
                    "Tea & Coffee Stations",
                    min_value=0, max_value=10,
                    value=1,
                    step=1,
                    key="packing_tc_stations"
                )
                water_stations = st.number_input(
                    "Water Stations",
                    min_value=0, max_value=10,
                    value=1,
                    step=1,
                    key="packing_water_stations"
                )
                has_tc = tc_stations > 0  # Auto-enable TC if stations > 0

            with opt_col3:
                st.markdown("**Display Options**")
                riser_color = st.radio(
                    "Riser Sets",
                    ["white", "black"],
                    horizontal=True,
                    format_func=lambda x: x.title(),
                    key="packing_riser_color"
                )

    # === PLENARY OPTIONS ===
    elif event_type == "plenary":
        # Sub-type selection
        sub_type = st.selectbox(
            "Plenary Style",
            options=list(PLENARY_SUB_TYPES.keys()),
            format_func=lambda x: PLENARY_SUB_TYPES[x],
            key="packing_plenary_subtype"
        )

        opt_col1, opt_col2 = st.columns(2)

        with opt_col1:
            st.markdown("**Table Linen**")
            linen_style = st.radio(
                "Linen Style",
                ["black_fitted", "white_fitted", "naked"],
                format_func=lambda x: {"black_fitted": "Black Fitted", "white_fitted": "White Fitted", "naked": "Naked Trestles"}[x],
                key="packing_linen_style"
            )

        with opt_col2:
            st.markdown("**Stations**")
            tc_stations = st.number_input(
                "Tea & Coffee Stations",
                min_value=0, max_value=10,
                value=0,
                step=1,
                key="packing_plenary_tc_stations"
            )
            has_tc = tc_stations > 0  # Auto-enable TC if stations > 0

    st.divider()

    # ============ GENERATE BUTTON ============
    if st.button("📋 Generate Packing List", type="primary", use_container_width=True):
        # For multi-meal buffets, use meal_sections_input; otherwise None
        multi_meal_sections = None
        if event_type == "buffet" and sub_type in MULTI_MEAL_CONFIGS:
            multi_meal_sections = meal_sections_input if meal_sections_input else None

        packing_list = generate_packing_list(
            event_name=event_name,
            event_date=event_date,
            location=location,
            pax=pax,
            tables=tables,
            event_type=event_type,
            sub_type=sub_type,
            # Plated options
            courses=courses,
            has_tc=has_tc,
            has_foh_bar=has_foh_bar,
            has_canapes=has_canapes,
            napkin_color=napkin_color,
            underliner_color=underliner_color,
            round_color=round_color,
            # Buffet options
            buffet_setups=buffet_setups,
            hot_items=hot_items,
            cold_items=cold_items,
            tc_stations=tc_stations,
            water_stations=water_stations,
            riser_color=riser_color,
            # Multi-meal buffet sections
            meal_sections_input=multi_meal_sections,
            # Plenary options
            trestle_count=trestle_count,
            linen_style=linen_style,
        )
        st.session_state.packing_list = packing_list
        st.rerun()

    # ============ STEP 4: REVIEW & EDIT ITEMS ============
    if st.session_state.packing_list:
        packing_list = st.session_state.packing_list

        st.markdown("### Step 4: Review & Adjust Items")

        # Event summary - dynamic based on event type
        event_type_label = EVENT_TYPES.get(packing_list.event_type, "Event")
        summary_line1 = f"**{packing_list.event_name}** | {packing_list.event_date} | {packing_list.location}"

        if packing_list.event_type == "plated":
            summary_line2 = f"**{packing_list.pax} pax** | **{packing_list.tables} tables** | {packing_list.courses} course | Napkins: {packing_list.napkin_color.title()}, Underliners: {packing_list.underliner_color.title()}, Rounds: {packing_list.round_color.title()}"
        elif packing_list.event_type == "buffet":
            sub_label = BUFFET_SUB_TYPES.get(packing_list.sub_type, packing_list.sub_type)
            if packing_list.meal_sections:
                # Multi-meal buffet
                section_names = ", ".join([s.name for s in packing_list.meal_sections])
                summary_line2 = f"**{packing_list.pax} pax** | {sub_label} | {len(packing_list.meal_sections)} meals"
            else:
                summary_line2 = f"**{packing_list.pax} pax** | {sub_label} | {packing_list.buffet_setups} setup(s) | Hot: {packing_list.hot_items}, Cold: {packing_list.cold_items}"
        elif packing_list.event_type == "plenary":
            sub_label = PLENARY_SUB_TYPES.get(packing_list.sub_type, packing_list.sub_type)
            summary_line2 = f"**{packing_list.pax} pax** | {sub_label} | {packing_list.trestle_count} trestles"
        else:
            summary_line2 = f"**{packing_list.pax} pax**"

        st.markdown(f"""
        {summary_line1}
        {summary_line2}
        """)

        st.divider()

        # Check if this is a multi-meal buffet
        if packing_list.meal_sections:
            # === MULTI-MEAL BUFFET: Display each meal section ===
            for section_idx, section in enumerate(packing_list.meal_sections):
                st.markdown(f"### {section.name}")
                st.caption(f"Setups: {section.buffet_setups} | Hot: {section.hot_items} | Cold: {section.cold_items} | Dessert: {section.dessert_items}")

                # Group items by category within this section
                section_items_by_cat = {}
                for item in section.items:
                    if item.category not in section_items_by_cat:
                        section_items_by_cat[item.category] = []
                    section_items_by_cat[item.category].append(item)

                for category in ["buffet_setup", "buffet_napkins"]:
                    items = section_items_by_cat.get(category, [])
                    active_items = [i for i in items if i.final_qty > 0]

                    if not active_items:
                        continue

                    category_label = BUFFET_CATEGORY_LABELS.get(category, category.replace("_", " ").title())
                    with st.expander(f"**{category_label}** ({len(active_items)} items)", expanded=True):
                        for i, item in enumerate(items):
                            if item.final_qty == 0 and category == "buffet_napkins":
                                continue

                            col1, col2, col3, col4 = st.columns([3, 1, 1, 2])

                            with col1:
                                st.markdown(f"**{item.name}**")

                            with col2:
                                st.caption(f"Suggested: {item.suggested_qty}")

                            with col3:
                                new_qty = st.number_input(
                                    "Qty",
                                    min_value=0,
                                    value=item.final_qty,
                                    step=1,
                                    key=f"qty_section_{section_idx}_{category}_{i}",
                                    label_visibility="collapsed"
                                )
                                if new_qty != item.final_qty:
                                    item.final_qty = new_qty

                            with col4:
                                if item.notes:
                                    st.caption(item.notes)

                st.divider()

            # === SHARED ITEMS (T&C Station, Water Station) ===
            st.markdown("### Shared Stations")

            items_by_cat = get_items_by_category(packing_list)
            category_labels = get_category_labels(packing_list.event_type)

            for category in ["tc_station", "water_station"]:
                items = items_by_cat.get(category, [])
                active_items = [i for i in items if i.final_qty > 0]

                if not active_items:
                    continue

                category_label = category_labels.get(category, category.replace("_", " ").title())
                with st.expander(f"**{category_label}** ({len(active_items)} items)", expanded=True):
                    for i, item in enumerate(items):
                        col1, col2, col3, col4 = st.columns([3, 1, 1, 2])

                        with col1:
                            st.markdown(f"**{item.name}**")

                        with col2:
                            st.caption(f"Suggested: {item.suggested_qty}")

                        with col3:
                            new_qty = st.number_input(
                                "Qty",
                                min_value=0,
                                value=item.final_qty,
                                step=1,
                                key=f"qty_shared_{category}_{i}",
                                label_visibility="collapsed"
                            )
                            if new_qty != item.final_qty:
                                item.final_qty = new_qty

                        with col4:
                            if item.notes:
                                st.caption(item.notes)

        else:
            # === SINGLE-MEAL OR OTHER EVENT TYPES ===
            items_by_cat = get_items_by_category(packing_list)
            category_order = get_category_order(packing_list.event_type)
            category_labels = get_category_labels(packing_list.event_type)

            # Optional categories to skip when empty
            optional_categories = ["bar_foh", "tc", "canape", "tc_station", "water_station"]

            for category in category_order:
                items = items_by_cat.get(category, [])
                # Only show categories with items that have qty > 0 or are always shown
                active_items = [i for i in items if i.final_qty > 0]

                if not active_items and category in optional_categories:
                    continue  # Skip empty optional categories

                category_label = category_labels.get(category, category.replace("_", " ").title())
                with st.expander(f"**{category_label}** ({len(active_items)} items)", expanded=True):
                    if not items:
                        st.caption("No items in this category")
                        continue

                    # Create editable table
                    for i, item in enumerate(items):
                        if item.final_qty == 0 and category in ["linen", "plenary_linen", "buffet_napkins"]:
                            # Skip zero-qty linen (wrong color/style)
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

    worksheet.write(row, 0, "EVENT TYPE:", header_fmt)
    event_type_label = EVENT_TYPES.get(packing_list.event_type, packing_list.event_type)
    if packing_list.sub_type:
        if packing_list.event_type == "buffet":
            sub_label = BUFFET_SUB_TYPES.get(packing_list.sub_type, packing_list.sub_type)
        else:
            sub_label = PLENARY_SUB_TYPES.get(packing_list.sub_type, packing_list.sub_type)
        event_type_label = f"{event_type_label} - {sub_label}"
    worksheet.write(row, 3, event_type_label)
    row += 1

    worksheet.write(row, 0, "GUEST COUNT:", header_fmt)
    worksheet.write(row, 1, packing_list.pax)
    row += 1

    # Show tables or trestles depending on event type
    if packing_list.event_type == "plenary":
        worksheet.write(row, 0, "TRESTLE COUNT:", header_fmt)
        worksheet.write(row, 1, packing_list.trestle_count)
    else:
        worksheet.write(row, 0, "TABLE COUNT:", header_fmt)
        worksheet.write(row, 1, packing_list.tables)
    row += 1

    worksheet.write(row, 0, "EVENT LOCATION:", header_fmt)
    worksheet.write(row, 3, packing_list.location)
    row += 1

    # Buffet-specific info (for single-meal buffets)
    if packing_list.event_type == "buffet" and not packing_list.meal_sections:
        worksheet.write(row, 0, "BUFFET SETUPS:", header_fmt)
        worksheet.write(row, 1, packing_list.buffet_setups)
        worksheet.write(row, 2, f"Hot: {packing_list.hot_items}")
        worksheet.write(row, 3, f"Cold: {packing_list.cold_items}")
        row += 1

    row += 1  # Empty row

    # Check if this is a multi-meal buffet
    if packing_list.meal_sections:
        # === MULTI-MEAL BUFFET: Write each meal section ===
        meal_section_fmt = workbook.add_format({"bold": True, "font_size": 14, "bg_color": "#4472C4", "font_color": "white"})

        for section in packing_list.meal_sections:
            # Section header (meal name)
            worksheet.write(row, 0, section.name.upper(), meal_section_fmt)
            worksheet.write(row, 1, "", meal_section_fmt)
            worksheet.write(row, 2, "", meal_section_fmt)
            worksheet.write(row, 3, "", meal_section_fmt)
            row += 1

            # Section setup info
            worksheet.write(row, 0, "Set Up", header_fmt)
            worksheet.write(row, 1, "QUANTITY", header_fmt)
            worksheet.write(row, 2, "PACKED (Y/N)", header_fmt)
            worksheet.write(row, 3, "NOTES", header_fmt)
            row += 1

            worksheet.write(row, 0, "Buffet Setups", cell_fmt)
            worksheet.write(row, 1, section.buffet_setups, qty_fmt)
            worksheet.write(row, 2, "", cell_fmt)
            worksheet.write(row, 3, "", cell_fmt)
            row += 1

            worksheet.write(row, 0, "Hot Menu Items", cell_fmt)
            worksheet.write(row, 1, section.hot_items, qty_fmt)
            worksheet.write(row, 2, "", cell_fmt)
            worksheet.write(row, 3, "", cell_fmt)
            row += 1

            worksheet.write(row, 0, "Cold Menu Items", cell_fmt)
            worksheet.write(row, 1, section.cold_items, qty_fmt)
            worksheet.write(row, 2, "", cell_fmt)
            worksheet.write(row, 3, "", cell_fmt)
            row += 1

            if section.dessert_items > 0:
                worksheet.write(row, 0, "Dessert Items", cell_fmt)
                worksheet.write(row, 1, section.dessert_items, qty_fmt)
                worksheet.write(row, 2, "", cell_fmt)
                worksheet.write(row, 3, "", cell_fmt)
                row += 1

            row += 1  # Empty row

            # Section items header
            worksheet.write(row, 0, f"{section.name}", section_fmt)
            worksheet.write(row, 1, "QUANTITY", section_fmt)
            worksheet.write(row, 2, "PACKED (Y/N)", section_fmt)
            worksheet.write(row, 3, "NOTES", section_fmt)
            row += 1

            # Section items
            for item in section.items:
                if item.final_qty > 0:
                    worksheet.write(row, 0, item.name, cell_fmt)
                    worksheet.write(row, 1, item.final_qty, qty_fmt)
                    worksheet.write(row, 2, "", cell_fmt)
                    worksheet.write(row, 3, item.notes, cell_fmt)
                    row += 1

            row += 1  # Empty row between sections

        # === SHARED ITEMS (T&C Station, Water Station) ===
        items_by_cat = get_items_by_category(packing_list)
        category_labels = get_category_labels(packing_list.event_type)

        for category in ["tc_station", "water_station"]:
            items = items_by_cat.get(category, [])
            active_items = [i for i in items if i.final_qty > 0]

            if not active_items:
                continue

            # Category header
            category_label = category_labels.get(category, category.replace("_", " ").title())
            worksheet.write(row, 0, category_label, section_fmt)
            worksheet.write(row, 1, "QUANTITY", section_fmt)
            worksheet.write(row, 2, "PACKED (Y/N)", section_fmt)
            worksheet.write(row, 3, "NOTES", section_fmt)
            row += 1

            # Items
            for item in active_items:
                worksheet.write(row, 0, item.name, cell_fmt)
                worksheet.write(row, 1, item.final_qty, qty_fmt)
                worksheet.write(row, 2, "", cell_fmt)
                worksheet.write(row, 3, item.notes, cell_fmt)
                row += 1

            row += 1  # Empty row between sections

    else:
        # === SINGLE-MEAL OR OTHER EVENT TYPES ===
        items_by_cat = get_items_by_category(packing_list)
        category_order = get_category_order(packing_list.event_type)
        category_labels = get_category_labels(packing_list.event_type)

        for category in category_order:
            items = items_by_cat.get(category, [])
            active_items = [i for i in items if i.final_qty > 0]

            if not active_items:
                continue

            # Category header
            category_label = category_labels.get(category, category.replace("_", " ").title())
            worksheet.write(row, 0, category_label, section_fmt)
            worksheet.write(row, 1, "QUANTITY", section_fmt)
            worksheet.write(row, 2, "PACKED (Y/N)", section_fmt)
            worksheet.write(row, 3, "NOTES", section_fmt)
            row += 1

            # Items
            for item in active_items:
                worksheet.write(row, 0, item.name, cell_fmt)
                worksheet.write(row, 1, item.final_qty, qty_fmt)
                worksheet.write(row, 2, "", cell_fmt)
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


def render_stocktake():
    """Stocktake inventory management page."""
    st.title("📦 Stocktake")

    # Initialize session state
    if "stocktake_items" not in st.session_state:
        st.session_state.stocktake_items = load_stocktake_items()
    if "stocktake_base" not in st.session_state:
        st.session_state.stocktake_base = load_base_items()
    if "stocktake_session" not in st.session_state:
        st.session_state.stocktake_session = None
    if "stocktake_dept" not in st.session_state:
        st.session_state.stocktake_dept = None

    items = st.session_state.stocktake_items
    base_items = st.session_state.stocktake_base

    # ============ NO ITEMS: IMPORT SECTION ============
    if not items:
        st.info("No inventory items loaded. Import from Excel to get started.")

        st.markdown("### Import Master Stocktake")

        uploaded_file = st.file_uploader(
            "Upload Stocktake Master Excel",
            type=["xlsx"],
            key="stocktake_import",
        )

        if uploaded_file is not None:
            if st.button("Import Items", type="primary"):
                with st.spinner("Importing..."):
                    # Save to temp file
                    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                        tmp.write(uploaded_file.read())
                        tmp_path = tmp.name

                    try:
                        imported = import_stocktake_excel(tmp_path)
                        save_stocktake_items(imported)
                        st.session_state.stocktake_items = imported
                        st.success(f"Imported {len(imported)} items!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Import failed: {e}")
                    finally:
                        os.unlink(tmp_path)
        return

    # ============ ITEMS LOADED: MAIN UI ============

    # Sidebar stats
    by_dept = get_items_by_department(items)
    st.sidebar.markdown("### Inventory Stats")
    st.sidebar.metric("Total Items", len(items))
    for dept_code, dept_name in DEPARTMENTS:
        if dept_code in by_dept:
            st.sidebar.caption(f"{dept_name}: {len(by_dept[dept_code])}")

    # Session management
    sessions = load_sessions()
    active_sessions = [s for s in sessions if s.status == "in_progress"]

    # Tabs for different modes
    tab1, tab2, tab3, tab4 = st.tabs(["Base", "Count Entry", "History", "Settings"])

    # ============ TAB 1: BASE (Jan 26 Reference Data) ============
    with tab1:
        st.markdown("### Base Inventory (Jan 26 Stocktake)")
        st.caption("Reference data from the Jan 26 stocktake. This is read-only.")

        if not base_items:
            st.warning("No base data loaded. Import the Jan 26 stocktake results below.")

            uploaded_base = st.file_uploader(
                "Upload Jan 26 Stocktake Results Excel",
                type=["xlsx"],
                key="base_import",
            )

            if uploaded_base is not None:
                if st.button("Import Base Data", type="primary"):
                    with st.spinner("Importing base data..."):
                        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                            tmp.write(uploaded_base.read())
                            tmp_path = tmp.name

                        try:
                            imported = import_base_from_excel(tmp_path)
                            save_base_items(imported)
                            st.session_state.stocktake_base = imported
                            st.success(f"Imported {len(imported)} base items!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Import failed: {e}")
                        finally:
                            os.unlink(tmp_path)
        else:
            # Show base items grouped by department
            base_by_dept = get_base_by_department(base_items)

            # Stats and re-upload option
            col_stat, col_upload = st.columns([2, 1])
            with col_stat:
                st.metric("Total Base Items", len(base_items))
            with col_upload:
                if st.button("Clear & Re-import", type="secondary"):
                    save_base_items([])
                    st.session_state.stocktake_base = []
                    st.rerun()

            # Search
            base_search = st.text_input("Search items", key="base_search", placeholder="Search by code or name...")

            # Department tabs for base data
            base_dept_list = [(d[0], d[1]) for d in DEPARTMENTS if d[0] in base_by_dept]
            if base_dept_list:
                base_dept_tabs = st.tabs([d[1] for d in base_dept_list])

                for tab_idx, (dept_code, dept_name) in enumerate(base_dept_list):
                    with base_dept_tabs[tab_idx]:
                        dept_base_items = base_by_dept[dept_code]

                        # Filter by search
                        if base_search:
                            dept_base_items = [
                                i for i in dept_base_items
                                if base_search.lower() in i.item_code.lower() or base_search.lower() in i.name.lower()
                            ]

                        if not dept_base_items:
                            st.info("No items match your search.")
                            continue

                        # Display as table with headers
                        st.markdown(f"**{len(dept_base_items)} items**")

                        # Column headers
                        header_col1, header_col2, header_col3, header_col4 = st.columns([3, 1, 1, 1])
                        with header_col1:
                            st.markdown("**Item**")
                        with header_col2:
                            st.markdown("**In-house**")
                        with header_col3:
                            st.markdown("**Warehouse**")
                        with header_col4:
                            st.markdown("**Total Stock**")

                        st.divider()

                        # Item rows
                        for item in dept_base_items:
                            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])

                            with col1:
                                st.markdown(f"**{item.name}**")
                                st.caption(f"{item.item_code}")

                            with col2:
                                st.markdown(f"{item.jan26_inhouse}")

                            with col3:
                                st.markdown(f"{item.warehouse}")

                            with col4:
                                st.markdown(f"**{item.total}**")

    # ============ TAB 2: COUNT ENTRY ============
    with tab2:
        # Session selector or create new
        col1, col2 = st.columns([3, 1])

        with col1:
            if active_sessions:
                session_options = ["New Session"] + [
                    f"{s.session_id} - {s.session_date} ({s.location})"
                    for s in active_sessions
                ]
                selected = st.selectbox("Session", session_options, key="session_select")

                if selected == "New Session":
                    st.session_state.stocktake_session = None
                else:
                    session_id = selected.split(" - ")[0]
                    st.session_state.stocktake_session = get_session(session_id)
            else:
                st.info("No active sessions. Create a new one to start counting.")

        with col2:
            if st.button("+ New Session", use_container_width=True):
                new_session = create_session(
                    session_date=datetime.now().date(),
                    location="Both",
                )
                save_session(new_session)
                st.session_state.stocktake_session = new_session
                st.rerun()

        session = st.session_state.stocktake_session

        if session is None:
            st.warning("Select or create a session to begin counting.")
            return

        st.divider()

        # Session info
        st.markdown(f"**Session:** {session.session_id} | **Date:** {session.session_date} | **Status:** {session.status}")

        # Department tabs
        dept_tabs = st.tabs([d[1] for d in DEPARTMENTS if d[0] in by_dept])

        for tab_idx, (dept_code, dept_name) in enumerate([(d[0], d[1]) for d in DEPARTMENTS if d[0] in by_dept]):
            with dept_tabs[tab_idx]:
                dept_items = by_dept[dept_code]

                # Group by category
                by_cat = get_stock_by_category(dept_items)
                categories = by_cat.get(dept_code, {"Uncategorized": dept_items})

                # Progress
                counted = sum(1 for item in dept_items if session.get_count(item.item_code).total > 0)
                st.progress(counted / len(dept_items) if dept_items else 0, text=f"{counted}/{len(dept_items)} items counted")

                # Search
                search = st.text_input("Search items", key=f"search_{dept_code}", placeholder="Search by code or name...")

                for cat_name, cat_items in categories.items():
                    # Filter by search
                    if search:
                        cat_items = [
                            i for i in cat_items
                            if search.lower() in i.item_code.lower() or search.lower() in i.name.lower()
                        ]
                        if not cat_items:
                            continue

                    with st.expander(f"**{cat_name}** ({len(cat_items)} items)", expanded=not search):
                        for item in cat_items:
                            count = session.get_count(item.item_code)
                            stock_down = count.stock_down(item.par_level)

                            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])

                            with col1:
                                # Show alert if below par
                                if stock_down > 0:
                                    st.markdown(f"🔴 **{item.name}**")
                                else:
                                    st.markdown(f"**{item.name}**")
                                st.caption(f"{item.item_code} | Par: {item.par_level}")

                            with col2:
                                new_warehouse = st.number_input(
                                    "Warehouse",
                                    min_value=0,
                                    value=count.warehouse,
                                    step=1,
                                    key=f"wh_{item.item_code}",
                                    label_visibility="collapsed",
                                )

                            with col3:
                                new_onsite = st.number_input(
                                    "Onsite",
                                    min_value=0,
                                    value=count.onsite,
                                    step=1,
                                    key=f"on_{item.item_code}",
                                    label_visibility="collapsed",
                                )

                            with col4:
                                total = new_warehouse + new_onsite
                                st.metric("Total", total, label_visibility="collapsed")

                            with col5:
                                new_stock_down = item.par_level - total
                                if new_stock_down > 0:
                                    st.markdown(f"⚠️ **-{new_stock_down}**")
                                elif new_stock_down < 0:
                                    st.markdown(f"📈 +{abs(new_stock_down)}")
                                else:
                                    st.markdown("✅ OK")

                            # Update if changed
                            if new_warehouse != count.warehouse or new_onsite != count.onsite:
                                session.set_count(item.item_code, new_warehouse, new_onsite)
                                save_session(session)

        st.divider()

        # Actions
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("💾 Save Progress", use_container_width=True):
                save_session(session)
                st.success("Saved!")

        with col2:
            if st.button("📊 Export Excel", use_container_width=True):
                excel_bytes = export_stocktake_excel(items, session)
                st.download_button(
                    "📥 Download",
                    data=excel_bytes,
                    file_name=f"stocktake_{session.session_id}_{session.session_date}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

        with col3:
            if st.button("✅ Complete Session", use_container_width=True):
                session.status = "completed"
                session.completed_by = "User"  # Could add user input
                save_session(session)
                st.session_state.stocktake_session = None
                st.success("Session completed!")
                st.rerun()

    # ============ TAB 3: HISTORY ============
    with tab3:
        st.markdown("### Session History")

        all_sessions = load_sessions()
        if not all_sessions:
            st.info("No stocktake sessions yet.")
        else:
            for s in sorted(all_sessions, key=lambda x: x.session_date, reverse=True):
                status_icon = "✅" if s.status == "completed" else "🔄"
                with st.expander(f"{status_icon} {s.session_date} - {s.session_id}"):
                    st.write(f"**Location:** {s.location}")
                    st.write(f"**Status:** {s.status}")
                    st.write(f"**Completed By:** {s.completed_by or 'N/A'}")

                    # Count summary
                    counted = sum(1 for c in s.counts.values() if c.total > 0)
                    st.write(f"**Items Counted:** {counted}")

                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("📊 Export", key=f"export_{s.session_id}"):
                            excel_bytes = export_stocktake_excel(items, s)
                            st.download_button(
                                "📥 Download",
                                data=excel_bytes,
                                file_name=f"stocktake_{s.session_id}_{s.session_date}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"dl_{s.session_id}",
                            )
                    with col2:
                        if s.status == "completed" and st.button("🔄 Reopen", key=f"reopen_{s.session_id}"):
                            s.status = "in_progress"
                            save_session(s)
                            st.rerun()

    # ============ TAB 4: SETTINGS ============
    with tab4:
        st.markdown("### Settings")

        st.markdown("#### Re-import Items")
        st.warning("This will replace all existing items with data from a new Excel file.")

        uploaded_file = st.file_uploader(
            "Upload New Stocktake Master",
            type=["xlsx"],
            key="stocktake_reimport",
        )

        if uploaded_file is not None:
            if st.button("Re-import Items", type="secondary"):
                with st.spinner("Importing..."):
                    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                        tmp.write(uploaded_file.read())
                        tmp_path = tmp.name

                    try:
                        imported = import_stocktake_excel(tmp_path)
                        save_stocktake_items(imported)
                        st.session_state.stocktake_items = imported
                        st.success(f"Re-imported {len(imported)} items!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Import failed: {e}")
                    finally:
                        os.unlink(tmp_path)

        st.divider()

        st.markdown("#### Danger Zone")
        if st.button("🗑️ Clear All Data", type="secondary"):
            if st.checkbox("I understand this will delete all stocktake data"):
                save_stocktake_items([])
                st.session_state.stocktake_items = []
                st.session_state.stocktake_session = None
                st.success("All data cleared!")
                st.rerun()


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
