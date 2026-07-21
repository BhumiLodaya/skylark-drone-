import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests


MONDAY_API_URL = "https://api.monday.com/v2"

DEALS_BOARD_ID = 5030093153
WORK_ORDERS_BOARD_ID = 5030093140


class MondayAPIError(RuntimeError):
    pass


def _get_api_token(api_token: Optional[str] = None) -> str:
    token = api_token or os.getenv("MONDAY_API_TOKEN")
    if not token:
        raise MondayAPIError(
            "Missing monday.com API token. Set MONDAY_API_TOKEN in your environment."
        )
    return token


def _extract_json_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, dict):
        if "text" in value:
            return value.get("text")
        if "value" in value:
            return value.get("value")
        return value

    return value


def _normalize_string(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        return re.sub(r"\s+", " ", value)
    return value


def _coerce_date_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    parsed = pd.to_datetime(series, errors="coerce", utc=False, infer_datetime_format=True)
    if hasattr(parsed, "dt"):
        try:
            return parsed.dt.tz_localize(None)
        except TypeError:
            return parsed
    return parsed


def _coerce_numeric_series(series: pd.Series) -> pd.Series:
    if series.empty:
        return series
    cleaned = (
        series.astype(str)
        .str.replace(r"[$,]", "", regex=True)
        .str.replace(r"\s+", "", regex=True)
        .replace({"None": None, "nan": None, "NaT": None, "": None})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _normalize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    normalized = df.copy()

    for column in normalized.columns:
        if normalized[column].dtype == "object":
            normalized[column] = normalized[column].map(_normalize_string)

    date_like_columns = [
        col
        for col in normalized.columns
        if any(token in col.lower() for token in ["date", "created", "updated", "closed", "start", "due"])
    ]
    for column in date_like_columns:
        normalized[column] = _coerce_date_series(normalized[column])

    numeric_like_columns = [
        col
        for col in normalized.columns
        if any(token in col.lower() for token in ["amount", "value", "price", "cost", "revenue", "deal size", "total"])
    ]
    for column in numeric_like_columns:
        if column in normalized.columns:
            normalized[column] = _coerce_numeric_series(normalized[column])

    normalized = normalized.replace(
        {
            "": None,
            "none": None,
            "null": None,
            "nan": None,
            "na": None,
            "n/a": None,
            "None": None,
            "Null": None,
            "N/A": None,
        }
    )

    for column in normalized.columns:
        if normalized[column].dtype == "object":
            normalized[column] = normalized[column].where(normalized[column].notna(), None)

    return normalized


def _graphql_request(query: str, variables: Optional[Dict[str, Any]] = None, api_token: Optional[str] = None) -> Dict[str, Any]:
    token = _get_api_token(api_token)
    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": variables or {}}

    response = requests.post(MONDAY_API_URL, json=payload, headers=headers, timeout=60)
    try:
        data = response.json()
    except Exception as exc:
        raise MondayAPIError(f"Invalid response from monday.com: {response.text[:500]}") from exc

    if response.status_code >= 400:
        raise MondayAPIError(f"monday.com HTTP error {response.status_code}: {data}")

    if "errors" in data and data["errors"]:
        raise MondayAPIError(f"monday.com GraphQL error: {data['errors']}")

    return data.get("data", {})


def _fetch_board_metadata(board_id: int, api_token: Optional[str] = None) -> Dict[str, Any]:
    query = """
    query ($board_id: [ID!]) {
      boards(ids: $board_id) {
        id
        name
        state
        columns {
          id
          title
          type
        }
      }
    }
    """
    data = _graphql_request(query, variables={"board_id": [board_id]}, api_token=api_token)
    boards = data.get("boards", [])
    if not boards:
        raise MondayAPIError(f"Board not found or inaccessible: {board_id}")
    return boards[0]


def _fetch_items_page(
    board_id: int,
    limit: int = 100,
    cursor: Optional[str] = None,
    api_token: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    query = """
    query ($board_id: [ID!], $limit: Int!, $cursor: String) {
      boards(ids: $board_id) {
        items_page(limit: $limit, cursor: $cursor) {
          cursor
          items {
            id
            name
            state
            created_at
            updated_at
            column_values {
              id
              text
              value
              type
            }
            group {
              id
              title
            }
          }
        }
      }
    }
    """
    variables = {"board_id": [board_id], "limit": limit, "cursor": cursor}
    data = _graphql_request(query, variables=variables, api_token=api_token)
    boards = data.get("boards", [])
    if not boards:
        return [], None

    page = boards[0].get("items_page") or {}
    items = page.get("items", []) or []
    next_cursor = page.get("cursor")
    return items, next_cursor


def _flatten_item(item: Dict[str, Any], column_map: Dict[str, str]) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "item_id": item.get("id"),
        "item_name": item.get("name"),
        "item_state": item.get("state"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "group_id": (item.get("group") or {}).get("id"),
        "group_name": (item.get("group") or {}).get("title"),
    }

    for column_value in item.get("column_values", []) or []:
        column_id = column_value.get("id")
        column_name = column_map.get(column_id, column_id)
        raw_value = column_value.get("text")
        if raw_value in (None, ""):
            raw_value = _extract_json_value(column_value.get("value"))
        row[column_name] = raw_value

    return row


def fetch_board_as_dataframe(
    board_id: int,
    api_token: Optional[str] = None,
    normalize: bool = True,
    page_size: int = 100,
    max_pages: Optional[int] = None,
) -> pd.DataFrame:
    """
    Fetch all items from a monday.com board and return a normalized DataFrame.

    Normalization steps:
    - Flattens column values into table columns
    - Coerces common date-like columns to datetime
    - Coerces common numeric-like columns to numeric
    - Standardizes empty/null-like strings to None
    - Preserves raw column names from monday.com
    """
    metadata = _fetch_board_metadata(board_id, api_token=api_token)
    column_map = {col["id"]: col["title"] for col in metadata.get("columns", [])}

    all_rows: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    page_count = 0

    while True:
        items, next_cursor = _fetch_items_page(
            board_id=board_id,
            limit=page_size,
            cursor=cursor,
            api_token=api_token,
        )
        for item in items:
            all_rows.append(_flatten_item(item, column_map))

        page_count += 1
        if not next_cursor or (max_pages is not None and page_count >= max_pages):
            break
        cursor = next_cursor

    df = pd.DataFrame(all_rows)

    if df.empty:
        return df

    if normalize:
        df = _normalize_dataframe(df)

    return df


def fetch_deals_dataframe(api_token: Optional[str] = None, normalize: bool = True) -> pd.DataFrame:
    return fetch_board_as_dataframe(
        board_id=DEALS_BOARD_ID,
        api_token=api_token,
        normalize=normalize,
    )


def fetch_work_orders_dataframe(api_token: Optional[str] = None, normalize: bool = True) -> pd.DataFrame:
    return fetch_board_as_dataframe(
        board_id=WORK_ORDERS_BOARD_ID,
        api_token=api_token,
        normalize=normalize,
    )


def fetch_both_boards(api_token: Optional[str] = None, normalize: bool = True) -> Dict[str, pd.DataFrame]:
    return {
        "deals": fetch_deals_dataframe(api_token=api_token, normalize=normalize),
        "work_orders": fetch_work_orders_dataframe(api_token=api_token, normalize=normalize),
    }


def summarize_data_quality(df: pd.DataFrame, board_name: str = "board") -> Dict[str, Any]:
    if df.empty:
        return {
            "board_name": board_name,
            "row_count": 0,
            "column_count": 0,
            "missing_fraction": 0.0,
            "warning": "No rows returned from monday.com.",
        }

    missing_fraction = float(df.isna().mean().mean()) if not df.empty else 0.0
    null_by_column = df.isna().mean().sort_values(ascending=False)
    top_missing = null_by_column.head(10).to_dict()

    return {
        "board_name": board_name,
        "row_count": int(df.shape[0]),
        "column_count": int(df.shape[1]),
        "missing_fraction": round(missing_fraction, 3),
        "top_missing_columns": {k: round(float(v), 3) for k, v in top_missing.items()},
    }


def build_leadership_update_payload(api_token: Optional[str] = None) -> Dict[str, Any]:
    boards = fetch_both_boards(api_token=api_token, normalize=True)
    deals_df = boards["deals"]
    work_orders_df = boards["work_orders"]

    return {
        "deals": deals_df,
        "work_orders": work_orders_df,
        "deals_quality": summarize_data_quality(deals_df, "deals"),
        "work_orders_quality": summarize_data_quality(work_orders_df, "work_orders"),
        "generated_at": datetime.utcnow().isoformat(),
    }
