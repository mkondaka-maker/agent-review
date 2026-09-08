# Financial Statement Review Agent

A web application that loads a financial-statement CSV, lets you pick a company and
year, accepts natural-language financial questions, runs deterministic Python
calculations, detects variances, generates charts, and uses an AI model (Claude) to
explain the results using only the evidence Python calculated.

**Python calculates. AI explains. Dataset provides evidence.**

---

## 1. Project structure

```
financial-review-agent/
├── backend/
│   ├── app.py                 Flask app + API endpoints
│   ├── agent.py                Intent detection + AI review generation
│   ├── data_loader.py          CSV loading/validation
│   ├── financial_analysis.py   YoY, growth rate, margin calculations
│   ├── validation.py           Missing data, duplicates, variances, anomalies
│   ├── chart_generator.py      Chart-ready JSON builders
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── script.js
├── data/
│   └── Financial_Statements.csv   ← sample data, replace with your real dataset
├── .env.example
└── README.md
```

## 2. What you MUST change before this is "yours"

These are the only things you need to touch to make this run for real:

1. **Your dataset** — `data/Financial_Statements.csv` currently contains a small
   *sample* dataset (Apple, Microsoft, Amazon, Tesla, 2019–2024) so the app runs
   out of the box. Replace this file with your real financial statement CSV.
   Keep the same header style — the app reads whatever columns exist, so as
   long as you have `Company` and `Year`, plus any of `Market Cap`, `Revenue`,
   `Gross Profit`, `Net Income`, `Earning Per Share`, `EBITDA`, and
   `Shareholder Equity`, everything downstream (KPIs, charts, margins) adapts
   automatically. Missing columns are skipped gracefully, not guessed.

2. **Your Anthropic API key** — copy `.env.example` to `.env` in the project
   root and set:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   Get a key at https://console.anthropic.com/. Without this, the dashboard
   still works fully (KPIs, charts, variance detection) — only the "AI
   Financial Review" section will show a graceful "temporarily unavailable"
   message instead of a written narrative, per the spec's error-handling rule.

3. **CORS / hosting origin** — if you deploy the frontend and backend on
   different domains (e.g. frontend on Vercel, backend on Render), edit
   `frontend/script.js`:
   ```js
   const API_BASE = ""; // change to "https://your-backend-domain.com"
   ```
   and restrict CORS in `backend/app.py` (`CORS(app)` currently allows all
   origins — fine for local dev, not for production).

4. **Variance threshold** (optional) — `backend/validation.py` has
   `VARIANCE_THRESHOLD_PCT = 20.0`. Adjust this to whatever percentage your
   business considers "significant."

## 3. Running it locally

```bash
cd financial-review-agent/backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp ../.env.example ../.env      # then edit ../.env with your API key
python app.py
```

Open **http://localhost:5000** — Flask serves the frontend directly, so there's
nothing extra to run for the UI. (If you prefer serving the frontend
separately, e.g. with `python -m http.server` from `frontend/`, just update
`API_BASE` in `script.js` to point at `http://localhost:5000`.)

## 4. Deploying online (what changes)

You need somewhere to run the Flask backend (it can't be static-hosted) plus
anywhere to serve the frontend (or let Flask keep serving it, as it does now).

Common options and what to change:

| Host | What you set |
|---|---|
| Render / Railway / Fly.io | Set `ANTHROPIC_API_KEY` as an environment variable in the dashboard; deploy `backend/` with `gunicorn app:app`. Add `gunicorn` to `requirements.txt`. |
| Vercel/Netlify (frontend only) + separate backend host | Set `API_BASE` in `script.js` to your backend's public URL; enable CORS for that specific origin in `app.py`. |
| A single VM (EC2, DigitalOcean, etc.) | Run behind `gunicorn` + `nginx`; put `.env` on the server, never commit it. |

**Never commit `.env` or your API key to version control.** `.env.example` is
a template only — the real `.env` should stay local/server-side and out of git
(add it to `.gitignore`).

## 5. How the pieces map to the spec

- `data_loader.py` → `load_dataset()`, `get_companies()`, `get_years()`,
  `get_company_data()`, `get_year_data()`, `get_previous_year_data()`
- `financial_analysis.py` → `calculate_yoy()`, `calculate_growth_rate()`,
  `calculate_margin()`, `compare_years()`
- `validation.py` → `detect_missing_values()`, duplicate detection,
  `detect_variances()`, `detect_anomalies()`
- `chart_generator.py` → `generate_chart_data()`-style builders for every
  chart type in the spec (revenue trend, net income trend, current-vs-previous,
  grouped bars, YoY bars, profitability line)
- `agent.py` → intent detection (keyword-based, auditable) +
  `generate_financial_review()`, which sends **only** the Python-calculated
  evidence to Claude and asks it to explain — never invent — numbers or causes
- `app.py` → wires it all together behind `/api/companies`, `/api/years`,
  `/api/financials`, `/api/analyze`

## 6. Error handling already built in

- No company/year/question selected → clear inline message, no crash.
- Metric missing from a record → simply omitted from KPI cards/charts, not
  faked.
- No previous year available → YoY charts/sections show "not available for
  comparison" instead of guessing.
- AI/API failure → the dashboard still renders all calculated values and
  charts; only the written narrative shows a fallback message.

## 7. Extending it

- Swap the keyword-based `detect_intent()` in `agent.py` for a Claude-based
  classifier if you want more flexible natural-language understanding — the
  function signature is already isolated so you can replace its body without
  touching `app.py`.
- Add more chart types by adding a function to `chart_generator.py` and wiring
  it into `app.py`'s `charts` dict and `script.js`'s render functions.
