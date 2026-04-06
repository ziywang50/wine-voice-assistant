import sqlite3
import json
import os
import requests
import pandas as pd
from io import StringIO

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

    _populate_filter_cache()


def _populate_filter_cache() -> None:
    """Cache distinct countries, regions, and varietals for pre-filtering."""
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


def query_wines(
    price_min: float | None = None,
    price_max: float | None = None,
    color: str | None = None,
    geo_term: str | None = None,
    varietal: str | None = None,
    order_by: str = "top_score DESC",
    limit: int = 50,
) -> list[dict]:
    conditions = []
    params: list = []

    if price_min is not None:
        conditions.append("price >= ?")
        params.append(price_min)
    if price_max is not None:
        conditions.append("price <= ?")
        params.append(price_max)
    if color:
        conditions.append("LOWER(color) = ?")
        params.append(color.lower())
    if geo_term:
        pattern = f"%{geo_term}%"
        conditions.append(
            "(LOWER(country) LIKE ? OR LOWER(region) LIKE ? OR LOWER(appellation) LIKE ?)"
        )
        params.extend([pattern, pattern, pattern])
    if varietal:
        conditions.append("LOWER(varietal) LIKE ?")
        params.append(f"%{varietal.lower()}%")

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"SELECT * FROM wines {where} ORDER BY {order_by} LIMIT ?"
    params.append(limit)

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def query_top_rated(limit: int = 100) -> list[dict]:
    """Return top-rated wines as a fallback when no filters match."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM wines WHERE top_score IS NOT NULL ORDER BY top_score DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
