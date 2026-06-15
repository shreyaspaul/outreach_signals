#!/usr/bin/env python3
"""
Column Utilities
Helper functions to auto-detect column names in CSVs for flexible input handling.
"""

import pandas as pd
from typing import Optional, Dict, List
import re


# Column name mappings: internal name -> list of possible column names (case-insensitive)
COLUMN_MAPPINGS = {
    'website': [
        'domain', 'website', 'url', 'site', 'web', 'company website',
        'company_website', 'site_url', 'homepage', 'web_address'
    ],
    'company_name': [
        'name', 'company name', 'company_name', 'organization', 'org',
        'company', 'business', 'business name', 'organization name'
    ],
    # Traffic columns that may already exist in the CSV
    'monthly_visits': [
        'monthly visits', 'monthly_visits', 'visits', 'monthly traffic',
        'monthly_traffic', 'traffic', 'visitors', 'monthly visitors'
    ],
    'bounce_rate': [
        'bounce rate', 'bounce_rate', 'bouncerate'
    ],
    'global_rank': [
        'global traffic rank', 'global_traffic_rank', 'global rank',
        'global_rank', 'rank', 'traffic rank', 'traffic_rank'
    ],
    'visit_duration': [
        'visit duration', 'visit_duration', 'avg visit duration',
        'average visit duration', 'time on site', 'session duration'
    ],
    'pages_per_visit': [
        'page views / visit', 'pages per visit', 'pages_per_visit',
        'pageviews per visit', 'pages/visit'
    ],
}


def find_column(df: pd.DataFrame, internal_name: str, required: bool = False) -> Optional[str]:
    """
    Find a column in the DataFrame that matches the internal name.

    Args:
        df: pandas DataFrame to search
        internal_name: Internal column name key from COLUMN_MAPPINGS
        required: If True, raise error if not found

    Returns:
        The actual column name in the DataFrame, or None if not found
    """
    if internal_name not in COLUMN_MAPPINGS:
        # If not in mappings, try direct match
        if internal_name in df.columns:
            return internal_name
        if required:
            raise ValueError(f"Column '{internal_name}' not found and no mapping defined")
        return None

    possible_names = COLUMN_MAPPINGS[internal_name]
    df_columns_lower = {col.lower().strip(): col for col in df.columns}

    for possible in possible_names:
        possible_lower = possible.lower().strip()
        if possible_lower in df_columns_lower:
            return df_columns_lower[possible_lower]

    if required:
        raise ValueError(
            f"Could not find column for '{internal_name}'. "
            f"Tried: {possible_names}. "
            f"Available columns: {list(df.columns)}"
        )

    return None


def get_website_column(df: pd.DataFrame) -> str:
    """Get the website/domain column name from DataFrame."""
    return find_column(df, 'website', required=True)


def get_company_column(df: pd.DataFrame) -> Optional[str]:
    """Get the company name column from DataFrame (optional)."""
    return find_column(df, 'company_name', required=False)


def get_value(row: pd.Series, df: pd.DataFrame, internal_name: str, default=None):
    """
    Get a value from a row using flexible column detection.

    Args:
        row: pandas Series (a row from the DataFrame)
        df: The parent DataFrame (needed for column detection)
        internal_name: Internal column name
        default: Default value if column not found
    """
    col = find_column(df, internal_name, required=False)
    if col and col in row.index:
        return row[col]
    return default


def detect_all_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    """
    Detect all mappable columns in a DataFrame.

    Returns:
        Dict mapping internal names to actual column names (or None if not found)
    """
    result = {}
    for internal_name in COLUMN_MAPPINGS.keys():
        result[internal_name] = find_column(df, internal_name, required=False)
    return result


def parse_traffic_value(value) -> Optional[int]:
    """
    Parse a traffic value that may be formatted with commas, as string, etc.

    Examples:
        "1,225" -> 1225
        "50,00,000" -> 5000000 (Indian format)
        1500 -> 1500
        "—" -> None
        None -> None
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        if pd.isna(value):
            return None
        return int(value)

    # Handle string values
    value_str = str(value).strip()

    # Check for empty/null indicators
    if value_str in ['', '—', '-', 'N/A', 'n/a', 'null', 'None', 'nan']:
        return None

    # Remove all commas and try to parse
    cleaned = value_str.replace(',', '')

    try:
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def parse_percentage(value) -> Optional[float]:
    """
    Parse a percentage value that may be formatted as string with % sign.

    Examples:
        "54.69%" -> 54.69
        54.69 -> 54.69
        "—" -> None
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        if pd.isna(value):
            return None
        return float(value)

    value_str = str(value).strip()

    if value_str in ['', '—', '-', 'N/A', 'n/a', 'null', 'None', 'nan']:
        return None

    # Remove % sign if present
    cleaned = value_str.replace('%', '').strip()

    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def extract_existing_traffic_data(row: pd.Series, df: pd.DataFrame) -> Dict:
    """
    Extract traffic data from existing CSV columns.

    Returns dict with standardized traffic metrics.
    """
    result = {
        'monthly_visits': None,
        'global_rank': None,
        'bounce_rate': None,
        'visit_duration': None,
        'pages_per_visit': None,
        'from_csv': True,  # Flag indicating data came from CSV, not API
        'error': None
    }

    # Monthly visits
    visits_col = find_column(df, 'monthly_visits')
    if visits_col:
        result['monthly_visits'] = parse_traffic_value(row.get(visits_col))

    # Global rank
    rank_col = find_column(df, 'global_rank')
    if rank_col:
        result['global_rank'] = parse_traffic_value(row.get(rank_col))

    # Bounce rate
    bounce_col = find_column(df, 'bounce_rate')
    if bounce_col:
        result['bounce_rate'] = parse_percentage(row.get(bounce_col))

    # Visit duration
    duration_col = find_column(df, 'visit_duration')
    if duration_col:
        result['visit_duration'] = parse_traffic_value(row.get(duration_col))

    return result


def has_traffic_data(df: pd.DataFrame) -> bool:
    """
    Check if the DataFrame already contains traffic data columns.
    """
    visits_col = find_column(df, 'monthly_visits')
    return visits_col is not None


def print_detected_columns(df: pd.DataFrame):
    """Print which columns were detected for debugging."""
    print("Detected columns:")
    detected = detect_all_columns(df)
    for internal, actual in detected.items():
        status = f"'{actual}'" if actual else "NOT FOUND"
        print(f"  {internal}: {status}")
