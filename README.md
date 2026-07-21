# Skylark

A small Streamlit-based utility for fetching and normalizing data from monday.com boards, producing quick data-quality summaries and leadership update payloads.

**Key Files**
- **`app.py`**: Streamlit application entry point. See [app.py](app.py).
- **`monday_api.py`**: monday.com API helpers and data-normalization utilities. See [monday_api.py](monday_api.py).
- **`agent.py`**: project agent/supporting scripts. See [agent.py](agent.py).
- **`test_key.py`**: quick test script used to validate configuration or keys. See [test_key.py](test_key.py).
- **`requirements.txt`**: Python dependencies. See [requirements.txt](requirements.txt).

**Overview**
- Fetches items from configured monday.com boards (DEALS and WORK_ORDERS).
- Normalizes and coerces common date and numeric fields into pandas-friendly formats.
- Produces lightweight data-quality summaries and payloads suitable for reporting or downstream processes.

**Prerequisites**
- Python 3.10+ (recommended)
- A valid monday.com API token with access to the boards defined in [monday_api.py](monday_api.py).
 - (Optional) A Google/Gemini API key if you plan to use the LLM agent features (`agent.py`).

**Configuration**
- Set the monday.com API token in your environment: `MONDAY_API_TOKEN`
  - Example (PowerShell):

```
$env:MONDAY_API_TOKEN = "your_token_here"
```

- If you want to use the LLM-powered agent in `agent.py` or run `test_key.py`, set one of the following environment variables instead of hardcoding keys:

```
setx GEMINI_API_KEY "your_api_key_here"
# or
setx GOOGLE_API_KEY "your_api_key_here"
```

Then restart your terminal/session so the variables are available.

Security note: Do NOT hardcode API keys in source files. Use environment variables or a secrets manager. `test_key.py` has been updated to read the key from `GEMINI_API_KEY` or `GOOGLE_API_KEY`.

**Installation**
1. Create and activate a virtual environment (recommended):

```
python -m venv .venv
.\.venv\Scripts\Activate.ps1     # PowerShell
# or
.\.venv\Scripts\activate.bat     # cmd
```

2. Install dependencies:

```
pip install -r requirements.txt
```

**Running the Streamlit App (Development)**

```
streamlit run app.py
```

Open the URL printed by Streamlit (usually `http://localhost:8501`).

**Running the quick test**
- To validate your API token or run the simple checks provided in the repo:

```
python test_key.py
```

**Project Structure (brief)**
- [app.py](app.py): UI and orchestration for interactive usage.
- [monday_api.py](monday_api.py): Core functions: `fetch_board_as_dataframe`, `fetch_deals_dataframe`, `fetch_work_orders_dataframe`, `summarize_data_quality`, and `build_leadership_update_payload`.
- [agent.py](agent.py): automation/agent helpers.

**Usage Tips**
- If you need to target a different monday.com board, update the board ID constants in [monday_api.py](monday_api.py).
- Use the pandas DataFrame output from `fetch_board_as_dataframe` for further analysis or export to CSV/Excel.

**Contributing**
- Send a pull request with clear intent and tests for non-trivial logic. Keep changes focused to one concern per PR.

**License & Contact**
- This repository does not include a license file. Add one if you intend to publish or share.
- For questions or help, open an issue in the repository or contact the maintainer.
