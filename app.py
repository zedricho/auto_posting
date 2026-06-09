"""Event Order Reconciliation Tool — Streamlit App."""

import streamlit as st

# Page config
st.set_page_config(
    page_title="EO Reconciliation Tool",
    page_icon="📊",
    layout="wide",
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
    st.title("📊 Event Order Reconciliation Tool")

    # Authentication
    if not check_password():
        st.stop()

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


def render_step_1_upload():
    """Step 1: Upload EO PDF and extract data."""
    st.header("Step 1: Upload & Extract")
    st.write("Upload an Event Order PDF to extract line items.")

    # Placeholder - will implement in next task
    st.info("PDF upload will be implemented in the next step.")

    if st.button("Skip to Step 2 (for testing)"):
        st.session_state.step = 2
        st.rerun()


def render_step_2_values():
    """Step 2: Enter consumption/cash values."""
    st.header("Step 2: Complete Values")
    st.write("Enter values for consumption and cash lines.")

    # Placeholder
    st.info("Value entry will be implemented in the next step.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back"):
            st.session_state.step = 1
            st.rerun()
    with col2:
        if st.button("Next →"):
            st.session_state.step = 3
            st.rerun()


def render_step_3_generate():
    """Step 3: Generate worksheet and download."""
    st.header("Step 3: Generate Worksheet")
    st.write("Review totals and download the worksheet.")

    # Placeholder
    st.info("Worksheet generation will be implemented in the next step.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back"):
            st.session_state.step = 2
            st.rerun()
    with col2:
        if st.button("Next →"):
            st.session_state.step = 4
            st.rerun()


def render_step_4_reconcile():
    """Step 4: Upload Delphi report and reconcile."""
    st.header("Step 4: Reconcile")
    st.write("Upload Delphi posting report and compare.")

    # Placeholder
    st.info("Reconciliation will be implemented in the next step.")

    if st.button("← Back"):
        st.session_state.step = 3
        st.rerun()

    if st.button("Start Over"):
        for key in list(st.session_state.keys()):
            if key != "authenticated":
                del st.session_state[key]
        st.rerun()


if __name__ == "__main__":
    main()
