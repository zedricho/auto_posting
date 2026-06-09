# Event Order Reconciliation Tool

A Streamlit web app for The Star Brisbane that automates the sales-posting workflow:

1. **Extract** line items from Event Order (EO) PDFs
2. **Enter** consumption and cash values
3. **Generate** reconciliation worksheets
4. **Reconcile** against Delphi posting reports

## Quick Start

### Local Development

```bash
# Clone the repo
git clone <your-repo-url>
cd event-recon

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up secrets
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit secrets.toml and set your password

# Run the app
streamlit run app.py
```

### Run Tests

```bash
pytest -v
```

## Deployment (Streamlit Community Cloud)

1. Push to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo
4. Set secrets in the Streamlit Cloud dashboard:
   - `password = "your-team-password"`
5. Deploy

## Project Structure

```
event-recon/
├── app.py                  # Streamlit app entry point
├── recon/
│   ├── models.py           # Pydantic data models
│   ├── parser.py           # PDF extraction
│   ├── builder.py          # Totals computation + Excel export
│   ├── reconciler.py       # Discrepancy detection
│   └── delphi_adapter.py   # Delphi report parsing
├── tests/                  # Test suite
└── docs/                   # Design specs and plans
```

## How It Works

### The Three Money Types

| Type | Trigger Phrase | Posts to Opera? |
|------|----------------|-----------------|
| Contracted | `@ $X` pricing | Yes |
| Consumption | "on consumption" | Yes |
| Cash | "at guest expense" | **No** |

**Delphi** includes all revenue. **Opera** excludes cash sales.

### Golden Test

The tool must reproduce the BEO 2895 example:
- Opera Total: **$205,230.63**
- Delphi Total: **$210,079.60**

The $4,848.97 difference is exactly the cash sale.

## License

Internal use only — The Star Brisbane
