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
        ["Overview", "Reconciliation"],
        label_visibility="collapsed",
    )

    if page == "Overview":
        render_overview()
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
    """Operations workflow overview page - visual flowchart with clickable nodes."""
    st.title("🏢 Operations Overview")

    # Load workflow data
    if "workflow_data" not in st.session_state:
        st.session_state.workflow_data = load_workflow()
    if "editing_node" not in st.session_state:
        st.session_state.editing_node = None

    workflow = st.session_state.workflow_data

    # Custom CSS for flowchart
    st.markdown("""
    <style>
    .flow-container {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: center;
        margin: 15px 0;
    }
    .flow-node {
        padding: 12px 18px;
        border-radius: 10px;
        text-align: center;
        font-weight: bold;
        font-size: 14px;
        border: 2px solid #333;
        cursor: pointer;
        transition: transform 0.2s, box-shadow 0.2s;
        min-width: 90px;
    }
    .flow-node:hover {
        transform: scale(1.05);
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    }
    .flow-node-key {
        border-width: 3px;
        font-size: 16px;
        padding: 14px 20px;
    }
    .flow-arrow {
        font-size: 24px;
        color: #555;
        margin: 0 8px;
    }
    .flow-section {
        background: #f8f9fa;
        border-radius: 12px;
        padding: 20px;
        margin: 15px 0;
    }
    .note-count {
        font-size: 11px;
        background: rgba(255,255,255,0.8);
        border-radius: 10px;
        padding: 2px 8px;
        margin-top: 5px;
        display: inline-block;
    }
    </style>
    """, unsafe_allow_html=True)

    # Legend with team colors
    st.markdown("##### Team Legend")
    legend_cols = st.columns(5)
    for i, (team, color) in enumerate(TEAM_COLORS.items()):
        dark_color = TEAM_COLORS_DARK[team]
        with legend_cols[i]:
            st.markdown(
                f'<div style="background: linear-gradient(135deg, {dark_color} 0%, {color} 100%); '
                f'padding: 8px 12px; border-radius: 8px; text-align: center; font-weight: bold; '
                f'border: 2px solid #333; font-size: 12px;">{TEAM_LABELS[team]}</div>',
                unsafe_allow_html=True
            )

    st.divider()

    # Helper to get node color
    def get_node_color(node):
        if node.is_key_member:
            return TEAM_COLORS_DARK.get(node.team, "#A9A9A9")
        return TEAM_COLORS.get(node.team, "#D3D3D3")

    # Helper to render clickable node button
    def render_node_button(node_id, col=None):
        node = workflow.get_node(node_id)
        if not node:
            return
        container = col if col else st
        color = get_node_color(node)
        is_key = node.is_key_member
        notes_text = f" 📝{len(node.notes)}" if node.notes else ""

        # Use a button styled to look like a node
        btn_label = f"{node.label}{notes_text}"
        if container.button(btn_label, key=f"node_btn_{node_id}", use_container_width=False):
            st.session_state.editing_node = node_id
            st.rerun()

    # ============ INTERCONNECTED FLOWCHART ============

    # --- SECTION 1: Sales & Planning (Left) + Operations (Right) ---
    st.markdown("### 📋 Sales, Planning & Operations")

    main_col1, arrow_col, main_col2 = st.columns([2, 0.3, 2])

    with main_col1:
        st.markdown('<div class="flow-section">', unsafe_allow_html=True)
        st.markdown("**Planning Path**")

        # Row 1: Sales
        c1, c2, c3 = st.columns([1, 0.3, 1])
        render_node_button("sales", c1)
        c2.markdown('<p style="text-align:center; font-size:20px;">→</p>', unsafe_allow_html=True)
        render_node_button("initial_event", c3)

        st.markdown('<p style="text-align:center; font-size:20px;">↓</p>', unsafe_allow_html=True)

        # Row 2: Delphi
        c1, c2, c3 = st.columns([1, 0.3, 1])
        render_node_button("delphi", c1)
        c2.markdown('<p style="text-align:center; font-size:20px;">↔</p>', unsafe_allow_html=True)
        render_node_button("daily_updates", c3)

        st.markdown('<p style="text-align:center; font-size:20px;">↓</p>', unsafe_allow_html=True)

        # Row 3: Planners (KEY)
        render_node_button("planners")

        st.markdown('<p style="text-align:center; font-size:20px;">↓</p>', unsafe_allow_html=True)

        # Row 4: Export
        render_node_button("export_eo")

        st.markdown('</div>', unsafe_allow_html=True)

    with arrow_col:
        st.markdown('<p style="text-align:center; font-size:30px; margin-top:150px;">→</p>', unsafe_allow_html=True)

    with main_col2:
        st.markdown('<div class="flow-section">', unsafe_allow_html=True)
        st.markdown("**Operations Path**")

        # Row 1: Rapid/Go
        render_node_button("rapid_go")

        st.markdown('<p style="text-align:center; font-size:20px;">↓</p>', unsafe_allow_html=True)

        # Row 2: Log Team (KEY) + Linen/Mobile
        c1, c2, c3 = st.columns(3)
        render_node_button("log_team", c1)
        render_node_button("linen_orders", c2)
        render_node_button("mobile_doc", c3)

        st.markdown('<p style="text-align:center; font-size:20px;">↓</p>', unsafe_allow_html=True)

        # Row 3: Outputs
        c1, c2, c3 = st.columns(3)
        render_node_button("packing_sheets", c1)
        render_node_button("room_flips", c2)
        render_node_button("asset_movement", c3)

        st.markdown('</div>', unsafe_allow_html=True)

    # --- SECTION 2: Management ---
    st.markdown("### 👔 Management & Rostering")

    st.markdown('<div class="flow-section">', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns([1.2, 0.3, 1, 1])
    render_node_button("management", c1)
    c2.markdown('<p style="text-align:center; font-size:20px;">→</p>', unsafe_allow_html=True)
    render_node_button("roster_build", c3)
    c4.markdown('<p style="color:#666; margin-top:10px;">(Labour %)</p>', unsafe_allow_html=True)

    st.markdown('<p style="text-align:center; font-size:20px;">↓</p>', unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 0.3, 1])
    render_node_button("plan_wtc", c1)
    c2.markdown('<p style="text-align:center; font-size:20px;">↔</p>', unsafe_allow_html=True)
    render_node_button("poa", c3)

    st.markdown('</div>', unsafe_allow_html=True)

    # --- SECTION 3: Floor Managers ---
    st.markdown("### 🎯 Floor Managers (FM) & Event Delivery")

    fm_col, delivery_col = st.columns([1.5, 1])

    with fm_col:
        st.markdown('<div class="flow-section">', unsafe_allow_html=True)
        st.markdown("**FM Operations**")

        c1, c2, c3 = st.columns([1, 0.3, 1])
        render_node_button("cross_checks", c1)
        c2.markdown('<p style="text-align:center; font-size:20px;">→</p>', unsafe_allow_html=True)
        render_node_button("postings", c3)

        st.markdown('<p style="text-align:center; font-size:20px;">↓</p>', unsafe_allow_html=True)

        c1, c2, c3 = st.columns([1, 0.3, 1])
        render_node_button("fm", c1)
        c2.markdown('<p style="text-align:center; font-size:20px;">↔</p>', unsafe_allow_html=True)
        render_node_button("opera", c3)

        st.markdown('<p style="text-align:center; font-size:20px;">↓</p>', unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        render_node_button("buildbooks", c1)
        render_node_button("fix_pay", c2)
        render_node_button("roster_issues", c3)
        render_node_button("function_report", c4)

        st.markdown('</div>', unsafe_allow_html=True)

    with delivery_col:
        st.markdown('<div class="flow-section">', unsafe_allow_html=True)
        st.markdown("**Event Delivery**")

        render_node_button("captains")

        st.markdown('<p style="text-align:center; font-size:20px;">↓</p>', unsafe_allow_html=True)

        render_node_button("floor_management")

        st.markdown("""
        <div style="margin-top: 15px; color: #666; font-size: 13px; padding: 10px; background: #fff; border-radius: 8px;">
            • Break allocations<br>
            • Set rooms & bars<br>
            • etc.
        </div>
        """, unsafe_allow_html=True)

        st.markdown('</div>', unsafe_allow_html=True)

    st.divider()

    # ============ NODE EDITOR (appears when node is clicked) ============
    if st.session_state.editing_node:
        node = workflow.get_node(st.session_state.editing_node)
        if node:
            st.markdown(f"### ✏️ Editing: {node.label}")

            edit_col1, edit_col2 = st.columns([1, 1])

            with edit_col1:
                color = get_node_color(node)
                st.markdown(
                    f'<div style="background-color: {color}; padding: 15px; border-radius: 10px; '
                    f'border: 3px solid #333; margin-bottom: 15px;">'
                    f'<strong style="font-size: 18px;">{node.label}</strong><br>'
                    f'<span style="color: #333;">Team: {TEAM_LABELS.get(node.team, node.team)}</span><br>'
                    f'<span style="color: #555;">{node.description}</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

                # Existing notes
                if node.notes:
                    st.markdown("**Notes:**")
                    for i, note in enumerate(node.notes):
                        nc1, nc2 = st.columns([5, 1])
                        with nc1:
                            st.markdown(f"📝 {note}")
                        with nc2:
                            if st.button("🗑️", key=f"del_note_{node.id}_{i}"):
                                node.notes.pop(i)
                                save_workflow(workflow)
                                st.rerun()
                else:
                    st.caption("No notes yet")

            with edit_col2:
                st.markdown("**Add a note:**")
                new_note = st.text_area("", placeholder="Type your note here...", key="edit_note_input", height=120)

                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("💾 Save Note", use_container_width=True):
                        if new_note.strip():
                            workflow.add_note(node.id, new_note.strip())
                            save_workflow(workflow)
                            st.success("Note saved!")
                            st.rerun()
                with bc2:
                    if st.button("✖️ Close", use_container_width=True):
                        st.session_state.editing_node = None
                        st.rerun()

            st.divider()

    # ============ ADD NEW NODE ============
    with st.expander("➕ Add New Node to Workflow"):
        nc1, nc2, nc3 = st.columns(3)
        with nc1:
            new_id = st.text_input("Node ID (unique, no spaces)", key="new_node_id")
            new_label = st.text_input("Display Label", key="new_node_label")
        with nc2:
            new_team = st.selectbox(
                "Team",
                options=list(TEAM_COLORS.keys()),
                format_func=lambda x: TEAM_LABELS.get(x, x),
                key="new_node_team",
            )
            new_is_key = st.checkbox("Key team member (darker color)", key="new_node_key")
        with nc3:
            new_desc = st.text_area("Description", key="new_node_desc", height=100)

        if st.button("Create Node", use_container_width=False):
            if new_id and new_label:
                if workflow.get_node(new_id):
                    st.error("Node ID already exists")
                else:
                    new_node = WorkflowNode(
                        id=new_id,
                        label=new_label,
                        team=new_team,
                        description=new_desc,
                        is_key_member=new_is_key,
                    )
                    workflow.add_node(new_node)
                    save_workflow(workflow)
                    st.success(f"Node '{new_label}' created!")
                    st.rerun()
            else:
                st.warning("ID and Label are required")

    # Footer
    st.divider()
    fc1, fc2 = st.columns([4, 1])
    with fc1:
        st.caption(f"Last updated: {workflow.last_updated[:19] if workflow.last_updated else 'Never'} | Click any node to edit")
    with fc2:
        if st.button("🔄 Reset"):
            workflow = get_default_workflow()
            save_workflow(workflow)
            st.session_state.workflow_data = workflow
            st.session_state.editing_node = None
            st.success("Reset!")
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
