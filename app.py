"""Event Order Reconciliation Tool — Streamlit App."""

import os
import tempfile
from datetime import datetime

import pandas as pd
import streamlit as st

from recon.parser import parse_pdf, parse_pdf_with_traces, ParseResult
from recon.builder import compute_totals, generate_excel
from recon.delphi_adapter import parse_delphi_report
from recon.reconciler import reconcile
from recon.feedback import FeedbackEntry, FeedbackLog, export_feedback_json
from recon.models import MatchTrace


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
        ["Reconciliation", "Parser Testing"],
        label_visibility="collapsed",
    )

    if page == "Reconciliation":
        render_reconciliation()
    else:
        render_parser_testing()


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


def render_parser_testing():
    """Parser testing page for refining extraction patterns."""
    st.title("🔬 Parser Testing")
    st.write("Upload EO PDFs to see detailed extraction traces and provide feedback.")

    # Initialize parser testing session state
    if "pt_result" not in st.session_state:
        st.session_state.pt_result = None
    if "pt_pdf_name" not in st.session_state:
        st.session_state.pt_pdf_name = None
    if "pt_feedback_log" not in st.session_state:
        st.session_state.pt_feedback_log = FeedbackLog()
    if "pt_notes" not in st.session_state:
        st.session_state.pt_notes = {}

    # Show feedback log status
    log = st.session_state.pt_feedback_log
    if log.entries:
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"**Feedback Log:** {len(log.entries)} entries")
        st.sidebar.markdown(f"PDFs: {', '.join(log.get_pdf_names())}")

    # Upload section
    st.subheader("1. Upload PDF")
    uploaded_file = st.file_uploader("Choose an EO PDF", type=["pdf"], key="pt_uploader")

    if uploaded_file is not None:
        if st.button("Extract with Traces"):
            with st.spinner("Extracting..."):
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(uploaded_file.read())
                    tmp_path = tmp.name

                try:
                    result = parse_pdf_with_traces(tmp_path)
                    st.session_state.pt_result = result
                    st.session_state.pt_pdf_name = uploaded_file.name
                    st.session_state.pt_notes = {}  # Reset notes for new PDF
                    st.success(f"Extracted {len(result.matched_lines)} matched lines, {len(result.unmatched_lines)} unmatched")
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    os.unlink(tmp_path)

    # Show results if available
    if st.session_state.pt_result is not None:
        result = st.session_state.pt_result
        pdf_name = st.session_state.pt_pdf_name

        # Event info
        st.divider()
        event = result.event_order
        st.subheader("Event Details")
        cols = st.columns(3)
        cols[0].metric("PM#", event.pm_number or "—")
        cols[1].metric("BEO#", event.beo_number or "—")
        cols[2].metric("Event", event.event_name or "—")

        # Matched lines table
        st.divider()
        st.subheader(f"2. Matched Lines ({len(result.matched_lines)})")

        for i, (raw_text, parsed, trace) in enumerate(result.matched_lines):
            with st.expander(f"**{parsed.description[:60]}...**" if len(parsed.description) > 60 else f"**{parsed.description}**"):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.markdown(f"**Pattern:** `{trace.pattern_name}`")
                    st.markdown(f"**Matched:** `{trace.matched_text}`")
                    st.markdown(f"**Extracted:** `{trace.extracted}`")
                    st.markdown(f"**Calculation:** {trace.calculation}")
                    st.markdown(f"**Value:** ${trace.value:,.2f}")
                    st.markdown(f"**Category:** {parsed.description}")
                with col2:
                    note_key = f"matched_{i}"
                    note = st.text_area(
                        "Feedback note",
                        value=st.session_state.pt_notes.get(note_key, ""),
                        key=f"note_{note_key}",
                        height=100,
                    )
                    st.session_state.pt_notes[note_key] = note

        # Unmatched lines
        if result.unmatched_lines:
            st.divider()
            st.subheader(f"3. Unmatched Lines ({len(result.unmatched_lines)})")
            st.warning("These lines look like they might contain pricing but didn't match any pattern.")

            for i, line in enumerate(result.unmatched_lines):
                with st.expander(f"**{line[:60]}...**" if len(line) > 60 else f"**{line}**"):
                    st.code(line)
                    note_key = f"unmatched_{i}"
                    note = st.text_area(
                        "What should this be?",
                        value=st.session_state.pt_notes.get(note_key, ""),
                        key=f"note_{note_key}",
                        height=100,
                    )
                    st.session_state.pt_notes[note_key] = note

        # Actions
        st.divider()
        st.subheader("4. Actions")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("Add to Feedback Log"):
                # Add matched lines with notes
                for i, (raw_text, parsed, trace) in enumerate(result.matched_lines):
                    note = st.session_state.pt_notes.get(f"matched_{i}", "")
                    if note:  # Only add if there's a note
                        entry = FeedbackEntry(
                            pdf_name=pdf_name,
                            line_text=raw_text,
                            match_trace=trace,
                            category=parsed.basis,
                            note=note,
                            timestamp=datetime.now().isoformat(),
                        )
                        log.add(entry)

                # Add unmatched lines with notes
                for i, line in enumerate(result.unmatched_lines):
                    note = st.session_state.pt_notes.get(f"unmatched_{i}", "")
                    if note:  # Only add if there's a note
                        entry = FeedbackEntry(
                            pdf_name=pdf_name,
                            line_text=line,
                            match_trace=None,
                            category=None,
                            note=note,
                            timestamp=datetime.now().isoformat(),
                        )
                        log.add(entry)

                st.success(f"Added to log. Total entries: {len(log.entries)}")
                st.rerun()

        with col2:
            if log.entries:
                json_data = export_feedback_json(log)
                st.download_button(
                    f"Download Feedback ({len(log.entries)} entries)",
                    data=json_data,
                    file_name=f"parser_feedback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                )

        with col3:
            if log.entries:
                if st.button("Clear Log"):
                    log.clear()
                    st.success("Log cleared")
                    st.rerun()


def render_step_1_upload():
    """Step 1: Upload EO PDF and extract data."""
    st.header("Step 1: Upload & Extract")
    st.write("Upload an Event Order PDF to extract line items.")

    uploaded_file = st.file_uploader("Choose an EO PDF", type=["pdf"])

    if uploaded_file is not None:
        if st.button("Extract"):
            with st.spinner("Extracting..."):
                # Save to temp file for pdfplumber
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(uploaded_file.read())
                    tmp_path = tmp.name

                try:
                    event_order = parse_pdf(tmp_path)
                    st.session_state.event_order = event_order
                    st.success(f"Extracted {len(event_order.line_items)} line items")
                except Exception as e:
                    st.error(f"Error extracting PDF: {e}")
                    return
                finally:
                    os.unlink(tmp_path)

    # Show extracted data if available
    if st.session_state.event_order is not None:
        event = st.session_state.event_order
        st.subheader("Event Details")
        col1, col2, col3 = st.columns(3)
        col1.metric("PM#", event.pm_number or "—")
        col2.metric("BEO#", event.beo_number or "—")
        col3.metric("Event", event.event_name or "—")

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
            df.drop(columns=["idx"]),
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
        # Check if all values are filled
        all_filled = all(item.value > 0 for _, item in needs_values)
        if all_filled:
            if st.button("Values Complete →"):
                st.session_state.step = 3
                st.rerun()
        else:
            st.button("Values Complete →", disabled=True)
            st.caption("Enter all values to continue")


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
