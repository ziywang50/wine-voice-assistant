import sqlite3
import json
import os
import requests
import pandas as pd

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "wines.db")
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "wines.csv")
CSV_URL = "https://docs.google.com/spreadsheets/d/1Bkv3Jb_8YuLUG2rWUhJhQBdaGjQCMFfwF9oJ5jrYDSA/export?format=csv"

SKIP_COLUMNS = {"Upc", "volume_ml"}

COLUMN_MAP = {
    "Id": "id",
    "Name": "name",
    "Producer": "producer",
    "Country": "country",
    "Region": "region",
    "Appellation": "appellation",
    "Varietal": "varietal",
    "Vintage": "vintage",
    "color": "color",
    "ABV": "abv",
    "Retail": "price",
    "professional_ratings": "ratings",
    "image_url": "image_url",
    "reference_url": "reference_url",
}

# Cache for distinct filter values, populated after DB init
_filter_cache: dict = {}


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _extract_top_score(ratings_str: str | None) -> int | None:
    if not ratings_str or pd.isna(ratings_str):
        return None
    try:
        ratings = json.loads(ratings_str)
        scores = [r.get("score") for r in ratings if isinstance(r.get("score"), (int, float))]
        return int(max(scores)) if scores else None
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def download_csv() -> None:
    """Download the wines CSV from Google Sheets if not already present."""
    if os.path.exists(CSV_PATH):
        print(f"[db] Using existing CSV at {CSV_PATH}")
        return
    print(f"[db] Downloading wines CSV from Google Sheets...")
    resp = requests.get(CSV_URL, timeout=30)
    resp.raise_for_status()
    with open(CSV_PATH, "w", encoding="utf-8") as f:
        f.write(resp.text)
    print(f"[db] CSV saved to {CSV_PATH}")


def init_db() -> None:
    """Download CSV (if needed), create DB, and import wines."""
    download_csv()

    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)

    # Drop skipped columns
    for col in SKIP_COLUMNS:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

    # Rename columns
    df.rename(columns=COLUMN_MAP, inplace=True)

    # Ensure required columns exist
    for col in ["id", "name", "price"]:
        if col not in df.columns:
            raise ValueError(f"Required column missing from CSV: {col}")

    # Convert price and abv to numeric
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    if "abv" in df.columns:
        df["abv"] = pd.to_numeric(df["abv"], errors="coerce")

    # Derive top_score
    ratings_col = df["ratings"] if "ratings" in df.columns else pd.Series([""] * len(df))
    df["top_score"] = ratings_col.apply(_extract_top_score)

    # Replace empty strings with None for nullable columns
    nullable_cols = ["producer", "country", "region", "appellation", "varietal",
                     "vintage", "color", "abv", "ratings", "image_url", "reference_url"]
    for col in nullable_cols:
        if col in df.columns:
            df[col] = df[col].replace("", None)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS wines")
        cur.execute("""
            CREATE TABLE wines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                producer TEXT,
                country TEXT,
                region TEXT,
                appellation TEXT,
                varietal TEXT,
                vintage TEXT,
                color TEXT,
                abv REAL,
                price REAL NOT NULL,
                ratings TEXT,
                top_score INTEGER,
                image_url TEXT,
                reference_url TEXT
            )
        """)

        rows = []
        for _, row in df.iterrows():
            # Skip rows without required fields
            if not row.get("id") or pd.isna(row.get("price")):
                continue
            rows.append((
                row.get("id"),
                row.get("name"),
                row.get("producer"),
                row.get("country"),
                row.get("region"),
                row.get("appellation"),
                row.get("varietal"),
                row.get("vintage"),
                row.get("color"),
                row.get("abv") if pd.notna(row.get("abv", None)) else None,
                row.get("price"),
                row.get("ratings"),
                row.get("top_score") if pd.notna(row.get("top_score", None)) else None,
                row.get("image_url"),
                row.get("reference_url"),
            ))

        cur.executemany("""
            INSERT OR REPLACE INTO wines
            (id, name, producer, country, region, appellation, varietal, vintage,
             color, abv, price, ratings, top_score, image_url, reference_url)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, rows)
        conn.commit()
        print(f"[db] Imported {len(rows)} wines into SQLite.")
    finally:
        conn.close()

    _load_valid_filters()


def _load_valid_filters() -> None:
    """Cache distinct countries, regions, appellations, and varietals for tool enum values."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT country FROM wines WHERE country IS NOT NULL")
        _filter_cache["countries"] = [r[0].lower() for r in cur.fetchall() if r[0]]

        cur.execute("SELECT DISTINCT region FROM wines WHERE region IS NOT NULL")
        _filter_cache["regions"] = [r[0].lower() for r in cur.fetchall() if r[0]]

        cur.execute("SELECT DISTINCT appellation FROM wines WHERE appellation IS NOT NULL")
        _filter_cache["appellations"] = [r[0].lower() for r in cur.fetchall() if r[0]]

        cur.execute("SELECT DISTINCT varietal FROM wines WHERE varietal IS NOT NULL")
        _filter_cache["varietals"] = [r[0].lower() for r in cur.fetchall() if r[0]]
    finally:
        conn.close()


def get_filter_cache() -> dict:
    return _filter_cache


ORDER_BY_MAP = {
    "score": "top_score DESC NULLS LAST",
    "price_asc": "price ASC",
    "price_desc": "price DESC",
}


def query_wines(
    name: str | None = None,
    producer: str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    color: str | None = None,
    country: str | None = None,
    region: str | None = None,
    appellation: str | None = None,
    varietal: str | None = None,
    vintage: str | None = None,
    abv_min: float | None = None,
    abv_max: float | None = None,
    order_by: str = "score",
    limit: int = 10,
) -> list[dict]:
    conditions = []
    params: list = []

    if name:
        conditions.append("LOWER(name) LIKE ?")
        params.append(f"%{name.lower()}%")
    if producer:
        conditions.append("LOWER(producer) LIKE ?")
        params.append(f"%{producer.lower()}%")
    if price_min is not None:
        conditions.append("price >= ?")
        params.append(price_min)
    if price_max is not None:
        conditions.append("price <= ?")
        params.append(price_max)
    if color:
        conditions.append("LOWER(color) = ?")
        params.append(color.lower())
    if country:
        conditions.append("LOWER(country) = ?")
        params.append(country.lower())
    if region:
        conditions.append("LOWER(region) LIKE ?")
        params.append(f"%{region.lower()}%")
    if appellation:
        conditions.append("LOWER(appellation) LIKE ?")
        params.append(f"%{appellation.lower()}%")
    if varietal:
        conditions.append("LOWER(varietal) LIKE ?")
        params.append(f"%{varietal.lower()}%")
    if vintage:
        conditions.append("vintage = ?")
        params.append(vintage)
    if abv_min is not None:
        conditions.append("abv >= ?")
        params.append(abv_min)
    if abv_max is not None:
        conditions.append("abv <= ?")
        params.append(abv_max)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql_order = ORDER_BY_MAP.get(order_by, ORDER_BY_MAP["score"])
    sql = f"SELECT * FROM wines {where} ORDER BY {sql_order} LIMIT ?"
    params.append(limit)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_wine_by_id(wine_id: str) -> dict | None:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM wines WHERE id = ?", (wine_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
