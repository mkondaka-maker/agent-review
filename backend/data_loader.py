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

DATA_PATH = os.environ.get(
    "FINANCIAL_CSV_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "Financial_Statements.csv"),
)

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


def load_dataset_from_db(db_url: str) -> pd.DataFrame:
    """Load dataset from PostgreSQL database using SQLAlchemy."""
    if not HAS_SQLALCHEMY:
        raise ImportError("sqlalchemy and psycopg2-binary are required to load from PostgreSQL database.")

    # Fix postgres:// URL prefix for SQLAlchemy 2.0+ compatibility
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    # Convert port 5432 to port 6543 (Supabase IPv4 session pooler port)
    # Render free tier instances lack IPv6 egress required by direct port 5432
    db_url_6543 = db_url.replace(":5432/", ":6543/").replace(":5432", ":6543")

    try:
        engine = create_engine(db_url_6543, pool_pre_ping=True, connect_args={"connect_timeout": 12})
        with engine.connect() as conn:
            df = pd.read_sql("SELECT * FROM financial_statements", conn)
    except Exception as e:
        print(f"[data_loader] Port 6543 connect failed ({e}), trying original URL...")
        engine = create_engine(db_url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            df = pd.read_sql("SELECT * FROM financial_statements", conn)

    # Map database snake_case column names to standard project column names
    df = df.rename(columns=DB_COLUMN_MAPPING)

    # Map Ticker symbols to clean company names if present
    if "Company" in df.columns:
        df["Company"] = df["Company"].map(lambda c: TICKER_TO_NAME.get(str(c).strip(), str(c).strip()))

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
