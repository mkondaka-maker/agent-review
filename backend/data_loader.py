"""
data_loader.py
Loads financial statement data from PostgreSQL (Supabase) if DATABASE_URL is set,
with automatic fallback to CSV if PostgreSQL is unavailable or unset.
"""

import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

try:
    from sqlalchemy import create_engine
    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

def get_csv_path() -> str:
    env_path = os.environ.get("FINANCIAL_CSV_PATH")
    candidates = []
    if env_path:
        candidates.extend([
            env_path,
            os.path.join(os.path.dirname(__file__), env_path),
            os.path.join(os.path.dirname(__file__), "..", env_path),
            os.path.join(os.getcwd(), env_path),
        ])
    candidates.extend([
        os.path.join(os.path.dirname(__file__), "..", "data", "Financial_Statements.csv"),
        os.path.join(os.path.dirname(__file__), "data", "Financial_Statements.csv"),
        os.path.join(os.getcwd(), "data", "Financial_Statements.csv"),
        os.path.join(os.getcwd(), "..", "data", "Financial_Statements.csv"),
    ])
    for c in candidates:
        if c and os.path.exists(c):
            return os.path.abspath(c)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "Financial_Statements.csv"))

DATA_PATH = get_csv_path()

# Columns we will treat as numeric financial metrics IF they exist in the dataset.
KNOWN_METRIC_COLUMNS = [
    "Market Cap",
    "Revenue",
    "Gross Profit",
    "Net Income",
    "Earning Per Share",
    "EBITDA",
    "Shareholder Equity",
    "Cash Flow Operating",
    "Cash Flow Investing",
    "Cash Flow Financial",
    "Current Ratio",
    "Debt Equity Ratio",
    "ROE",
    "ROA",
    "ROI",
    "Net Profit Margin",
    "Free Cash Flow Per Share",
    "Number of Employees",
]

# Column name mapping from database snake_case to human-readable Title Case
DB_COLUMN_MAPPING = {
    "company": "Company",
    "year": "Year",
    "category": "Category",
    "market_cap_b_usd": "Market Cap",
    "revenue": "Revenue",
    "gross_profit": "Gross Profit",
    "net_income": "Net Income",
    "earning_per_share": "Earning Per Share",
    "ebitda": "EBITDA",
    "shareholder_equity": "Shareholder Equity",
    "cash_flow_operating": "Cash Flow Operating",
    "cash_flow_investing": "Cash Flow Investing",
    "cash_flow_financial_activities": "Cash Flow Financial",
    "current_ratio": "Current Ratio",
    "debt_equity_ratio": "Debt Equity Ratio",
    "roe": "ROE",
    "roa": "ROA",
    "roi": "ROI",
    "net_profit_margin": "Net Profit Margin",
    "free_cash_flow_per_share": "Free Cash Flow Per Share",
    "return_on_tangible_equity": "Return on Tangible Equity",
    "number_of_employees": "Number of Employees",
    "inflation_rate_in_us": "Inflation Rate (US)",
}

_cache = {"df": None, "source": None}


# Mapping Ticker Symbols (from Supabase DB) to Full Company Names
TICKER_TO_NAME = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "GOOG": "Google",
    "NVDA": "Nvidia",
    "PYPL": "PayPal",
    "MCD": "McDonald's",
    "INTC": "Intel",
    "SHLDQ": "Sears",
    "BCS": "Barclays",
    "PCG": "PG&E",
    "AIG": "AIG",
}


def normalize_supabase_url(db_url: str) -> str:
    if not db_url:
        return db_url
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    # Auto-rewrite legacy IPv6 direct host (db.<ref>.supabase.co) to active IPv4 pooler
    import re
    m = re.search(r"@db\.([a-z0-9]+)\.supabase\.co(?::\d+)?", db_url)
    if m:
        ref = m.group(1)
        if f"postgres.{ref}:" not in db_url:
            db_url = re.sub(r"postgresql://postgres:", f"postgresql://postgres.{ref}:", db_url)
        db_url = re.sub(r"@db\.[a-z0-9]+\.supabase\.co(?::\d+)?", "@aws-0-ap-southeast-1.pooler.supabase.com:6543", db_url)
    elif ":5432" in db_url:
        db_url = db_url.replace(":5432/", ":6543/").replace(":5432", ":6543")
    return db_url


def load_dataset_from_db(db_url: str) -> pd.DataFrame:
    """Load dataset from PostgreSQL / Supabase using SQLAlchemy."""
    if not HAS_SQLALCHEMY:
        raise ImportError("sqlalchemy and psycopg2-binary are required.")

    db_url_pooler = normalize_supabase_url(db_url)
    print(f"[data_loader] Connecting to Supabase (pooler URL): {db_url_pooler[:60]}...")

    engine = create_engine(
        db_url_pooler,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 15},
    )
    with engine.connect() as conn:
        df = pd.read_sql("SELECT * FROM financial_statements", conn)

    print(f"[data_loader] DB query returned {len(df)} rows, columns: {list(df.columns)}")

    # Map database snake_case column names to standard project column names
    df = df.rename(columns=DB_COLUMN_MAPPING)

    # Map Ticker symbols to clean company names if present
    if "Company" in df.columns:
        df["Company"] = df["Company"].map(
            lambda c: TICKER_TO_NAME.get(str(c).strip(), str(c).strip())
        )

    return df


def load_dataset(force_reload: bool = False) -> pd.DataFrame:
    """
    Load dataset into a DataFrame.
    Tries PostgreSQL DB first if DATABASE_URL is set, falling back to CSV.
    """
    if _cache["df"] is not None and not force_reload:
        return _cache["df"]

    db_url = os.environ.get("DATABASE_URL")
    df = None
    loaded_source = None

    # Prioritize PostgreSQL database (DATABASE_URL), fallback to local CSV if unavailable or connection fails
    if db_url and HAS_SQLALCHEMY:
        try:
            df = load_dataset_from_db(db_url)
            loaded_source = "postgresql"
            print(f"[data_loader] Successfully loaded {len(df)} rows from PostgreSQL database.")
        except Exception as err:
            print(f"[data_loader] PostgreSQL load failed ({err}). Falling back to CSV...")
            df = None

    if df is None:
        if not os.path.exists(DATA_PATH):
            raise FileNotFoundError(
                f"Dataset not found at {DATA_PATH}. Place your CSV there or set DATABASE_URL / FINANCIAL_CSV_PATH."
            )
        df = pd.read_csv(DATA_PATH)
        loaded_source = "csv"
        print(f"[data_loader] Loaded {len(df)} rows from local CSV.")

    # Normalize column names (strip whitespace) but keep human-readable labels.
    df.columns = [c.strip() for c in df.columns]

    if "Company" not in df.columns or "Year" not in df.columns:
        raise ValueError("Dataset must contain at least 'Company' and 'Year' columns.")

    # Ensure numeric columns are properly typed using loc to avoid pandas chained assignment warnings
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce")

    for col in KNOWN_METRIC_COLUMNS:
        if col in df.columns:
            df.loc[:, col] = pd.to_numeric(df[col], errors="coerce")

    _cache["df"] = df
    _cache["source"] = loaded_source
    return df


def get_data_source() -> str:
    """Return 'postgresql' or 'csv' depending on active dataset source."""
    if _cache["source"] is None:
        load_dataset()
    return _cache["source"] or "unknown"


def get_available_metric_columns(df: pd.DataFrame = None) -> list:
    """Return only the known metric columns that actually exist in this dataset."""
    if df is None:
        df = load_dataset()
    return [c for c in KNOWN_METRIC_COLUMNS if c in df.columns]


def get_companies() -> list:
    df = load_dataset()
    return sorted(df["Company"].dropna().unique().tolist())


def get_years(company: str = None) -> list:
    df = load_dataset()
    if company:
        df = df[df["Company"] == company]
    years = df["Year"].dropna().unique().tolist()
    return sorted(int(y) for y in years)


def get_company_data(company: str) -> pd.DataFrame:
    df = load_dataset()
    result = df[df["Company"] == company].sort_values("Year")
    if result.empty:
        raise ValueError(f"No data found for company '{company}'.")
    return result


def get_year_data(company: str, year: int) -> dict:
    df = load_dataset()
    row = df[(df["Company"] == company) & (df["Year"] == int(year))]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def get_previous_year_data(company: str, year: int) -> dict:
    """Return the most recent available year strictly before `year` for this company."""
    df = load_dataset()
    subset = df[(df["Company"] == company) & (df["Year"] < int(year))]
    if subset.empty:
        return None
    prev_row = subset.sort_values("Year").iloc[-1]
    return prev_row.to_dict()


def get_years_in_range(company: str, start_year: int, end_year: int) -> pd.DataFrame:
    df = load_dataset()
    subset = df[
        (df["Company"] == company)
        & (df["Year"] >= int(start_year))
        & (df["Year"] <= int(end_year))
    ].sort_values("Year")
    return subset


def get_latest_year(company: str = None) -> int:
    """Return the most recent available year for a company (or dataset)."""
    df = load_dataset()
    if company:
        subset = df[df["Company"] == company]
        if not subset.empty and subset["Year"].dropna().any():
            return int(subset["Year"].dropna().max())
    if not df.empty and df["Year"].dropna().any():
        return int(df["Year"].dropna().max())
    return 2024


def find_canonical_company(query_name: str, df: pd.DataFrame = None) -> str:
    """Resolve a company name / ticker / alias against active database companies."""
    if not query_name:
        return None
    if df is None:
        df = load_dataset()
    
    companies = get_companies()
    q = str(query_name).strip().lower()

    # 1. Exact match (case-insensitive)
    for c in companies:
        if c.lower() == q:
            return c

    # 2. Ticker match
    for ticker, name in TICKER_TO_NAME.items():
        if ticker.lower() == q:
            if name in companies:
                return name
            return name

    # 3. Substring match
    for c in companies:
        if c.lower() in q or q in c.lower():
            return c

    # 4. Fuzzy match
    import difflib
    matches = difflib.get_close_matches(query_name, companies, n=1, cutoff=0.6)
    if matches:
        return matches[0]

    return None


def search_financial_database(
    company: str,
    year: int = None,
    comparison_year: int = None,
    comparison_company: str = None,
) -> dict:
    """
    Rich query interface for PostgreSQL (Supabase) financial statements.
    Retrieves primary record, comparison record, multi-year history, and optional cross-company data.
    """
    df = load_dataset()
    available_companies = get_companies()

    # 1. Resolve Primary Company
    resolved_company = find_canonical_company(company, df) or company
    if resolved_company not in available_companies and available_companies:
        # Fallback to closest or first available
        import difflib
        matches = difflib.get_close_matches(str(company), available_companies, n=1, cutoff=0.4)
        resolved_company = matches[0] if matches else available_companies[0]

    company_years = get_years(resolved_company)
    if not company_years:
        raise ValueError(f"No records found in database for company: {resolved_company}")

    # 2. Resolve Target Year
    requested_year = year
    actual_year = year
    year_fallback_note = None

    if actual_year is None or actual_year not in company_years:
        if actual_year is not None:
            # Find closest available year in database
            closest_year = min(company_years, key=lambda y: abs(y - actual_year))
            year_fallback_note = f"Requested FY{actual_year} not in database; using closest available FY{closest_year}."
            actual_year = closest_year
        else:
            actual_year = max(company_years)

    actual_year = int(actual_year)
    current_record = get_year_data(resolved_company, actual_year)

    # 3. Resolve Comparison Year
    actual_prev_year = None
    if comparison_year is not None:
        if int(comparison_year) in company_years:
            actual_prev_year = int(comparison_year)
        else:
            # Pick closest year before target year
            candidates = [y for y in company_years if y < actual_year]
            if candidates:
                actual_prev_year = max(candidates)
    else:
        # Default previous available year
        candidates = [y for y in company_years if y < actual_year]
        if candidates:
            actual_prev_year = max(candidates)

    previous_record = get_year_data(resolved_company, actual_prev_year) if actual_prev_year else None

    # 4. Multi-year history (all available years for this company)
    company_history_df = get_company_data(resolved_company)
    company_history = company_history_df.to_dict("records")

    # 5. Optional Comparison Company Search
    comp_company_data = None
    if comparison_company:
        resolved_comp_company = find_canonical_company(comparison_company, df)
        if resolved_comp_company and resolved_comp_company != resolved_company:
            comp_years = get_years(resolved_comp_company)
            comp_target_year = actual_year if actual_year in comp_years else (max(comp_years) if comp_years else None)
            if comp_target_year:
                comp_record = get_year_data(resolved_comp_company, comp_target_year)
                comp_company_data = {
                    "company": resolved_comp_company,
                    "year": comp_target_year,
                    "record": comp_record,
                    "available_years": comp_years,
                }

    return {
        "primary_company": resolved_company,
        "target_year": actual_year,
        "requested_year": requested_year,
        "previous_year": actual_prev_year,
        "year_fallback_note": year_fallback_note,
        "current_record": current_record,
        "previous_record": previous_record,
        "available_years": company_years,
        "history": company_history,
        "comparison_company_data": comp_company_data,
        "data_source": get_data_source(),
    }


