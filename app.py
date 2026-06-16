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
    WorkflowNode, WorkflowData, TEAM_COLORS, TEAM_LABELS,
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
    """Operations workflow overview page."""
    st.title("🏢 Operations Overview")
    st.write("Interactive workflow diagram showing how teams and processes connect.")

    # Load workflow data
    if "workflow_data" not in st.session_state:
        st.session_state.workflow_data = load_workflow()

    workflow = st.session_state.workflow_data

    # Sidebar controls
    st.sidebar.markdown("---")
    st.sidebar.subheader("Workflow Controls")

    # Node selector
    node_options = {n.id: n.label for n in workflow.nodes}
    selected_node_id = st.sidebar.selectbox(
        "Select Node",
        options=list(node_options.keys()),
        format_func=lambda x: node_options[x],
        key="selected_node",
    )

    selected_node = workflow.get_node(selected_node_id)

    if selected_node:
        st.sidebar.markdown(f"**Team:** {TEAM_LABELS.get(selected_node.team, selected_node.team)}")
        st.sidebar.markdown(f"**Description:** {selected_node.description or 'No description'}")

        # Notes section
        st.sidebar.markdown("**Notes:**")
        if selected_node.notes:
            for i, note in enumerate(selected_node.notes):
                st.sidebar.markdown(f"- {note}")
        else:
            st.sidebar.caption("No notes yet")

        # Add note
        with st.sidebar.expander("Add Note"):
            new_note = st.text_area("Note", key="new_note_input", height=80)
            if st.button("Add Note"):
                if new_note.strip():
                    workflow.add_note(selected_node_id, new_note.strip())
                    save_workflow(workflow)
                    st.session_state.workflow_data = workflow
                    st.success("Note added!")
                    st.rerun()

    # Add new node
    with st.sidebar.expander("Add New Node"):
        new_id = st.text_input("ID (unique)", key="new_node_id")
        new_label = st.text_input("Label", key="new_node_label")
        new_team = st.selectbox(
            "Team",
            options=list(TEAM_COLORS.keys()),
            format_func=lambda x: TEAM_LABELS.get(x, x),
            key="new_node_team",
        )
        new_desc = st.text_area("Description", key="new_node_desc", height=60)

        if st.button("Create Node"):
            if new_id and new_label:
                if workflow.get_node(new_id):
                    st.error("Node ID already exists")
                else:
                    new_node = WorkflowNode(
                        id=new_id,
                        label=new_label,
                        team=new_team,
                        description=new_desc,
                        row=12,  # Add to bottom
                        col=0,
                    )
                    workflow.add_node(new_node)
                    save_workflow(workflow)
                    st.session_state.workflow_data = workflow
                    st.success(f"Node '{new_label}' created!")
                    st.rerun()
            else:
                st.warning("ID and Label are required")

    # Reset to default
    if st.sidebar.button("Reset to Default"):
        workflow = get_default_workflow()
        save_workflow(workflow)
        st.session_state.workflow_data = workflow
        st.success("Reset to default workflow")
        st.rerun()

    # Main content - Legend
    st.subheader("Team Legend")
    legend_cols = st.columns(len(TEAM_COLORS))
    for i, (team_id, color) in enumerate(TEAM_COLORS.items()):
        with legend_cols[i]:
            st.markdown(
                f'<div style="background-color: {color}; padding: 8px; border-radius: 4px; text-align: center; font-weight: bold;">'
                f'{TEAM_LABELS.get(team_id, team_id)}</div>',
                unsafe_allow_html=True,
            )

    st.divider()

    # Display workflow as organized sections by team
    st.subheader("Workflow Diagram")

    # Group nodes by team
    nodes_by_team = {}
    for node in workflow.nodes:
        if node.team not in nodes_by_team:
            nodes_by_team[node.team] = []
        nodes_by_team[node.team].append(node)

    # Display each team's nodes
    for team_id in TEAM_COLORS.keys():
        if team_id not in nodes_by_team:
            continue

        team_nodes = nodes_by_team[team_id]
        color = TEAM_COLORS[team_id]

        with st.expander(f"**{TEAM_LABELS.get(team_id, team_id)}** ({len(team_nodes)} nodes)", expanded=True):
            # Display nodes in a grid
            cols_per_row = 4
            for i in range(0, len(team_nodes), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, col in enumerate(cols):
                    if i + j < len(team_nodes):
                        node = team_nodes[i + j]
                        with col:
                            # Node card
                            is_selected = node.id == selected_node_id
                            border = "3px solid #333" if is_selected else "1px solid #ccc"
                            st.markdown(
                                f'''<div style="
                                    background-color: {color};
                                    padding: 12px;
                                    border-radius: 8px;
                                    border: {border};
                                    margin-bottom: 8px;
                                    min-height: 80px;
                                ">
                                    <strong>{node.label}</strong>
                                    <br><small>{node.description[:50]}{"..." if len(node.description) > 50 else ""}</small>
                                    {f'<br><small>📝 {len(node.notes)} notes</small>' if node.notes else ''}
                                </div>''',
                                unsafe_allow_html=True,
                            )

                            # Show connections if any
                            if node.connections:
                                conn_labels = [
                                    workflow.get_node(c).label if workflow.get_node(c) else c
                                    for c in node.connections
                                ]
                                st.caption(f"→ {', '.join(conn_labels)}")

    # Footer with metadata
    st.divider()
    st.caption(f"Last updated: {workflow.last_updated[:19] if workflow.last_updated else 'Never'}")


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
