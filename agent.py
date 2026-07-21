import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from langchain_google_genai import ChatGoogleGenerativeAI

from monday_api import DEALS_BOARD_ID, WORK_ORDERS_BOARD_ID, fetch_board_as_dataframe


SYSTEM_PROMPT = (
    "You are a business intelligence analyst for monday.com data. "
    "Use only the provided board data. If the request is vague, ask one clarifying question. "
    "Always mention data quality caveats. If the user asks for a leadership update or executive summary, "
    "combine both boards and return a concise Markdown report with revenue/pipeline, bottlenecks, sector performance, and executive takeaways."
)

AMBIGUOUS_HINTS = (
    "how are we doing",
    "status",
    "update",
    "what's happening",
    "what is happening",
    "performance",
    "anything interesting",
    "help me understand",
    "tell me about",
)

LEADERSHIP_HINTS = (
    "leadership update",
    "executive update",
    "exec update",
    "executive summary",
    "board update",
    "weekly leadership",
    "leadership report",
    "exec report",
    "business update",
)


@dataclass
class AgentResponse:
    content: str
    needs_clarification: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


def _safe_text(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    return text or None


def _find_column(df: pd.DataFrame, keywords: Sequence[str]) -> Optional[str]:
    for keyword in keywords:
        needle = keyword.lower().strip()
        for column in df.columns:
            label = re.sub(r"[^a-z0-9]+", " ", str(column).lower()).strip()
            if needle and needle in label:
                return column
    return None


def _to_numeric(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(r"[$,]", "", regex=True)
        .str.replace(r"\s+", "", regex=True)
        .replace({"None": None, "nan": None, "NaT": None, "": None})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _to_datetime(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce")


def _format_currency(value: Optional[float]) -> str:
    return "n/a" if value is None or pd.isna(value) else f"${value:,.0f}"


def _format_number(value: Optional[float]) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"


def _quality_caveats(df: pd.DataFrame, amount_column: Optional[str] = None, status_column: Optional[str] = None, date_column: Optional[str] = None, label: str = "board") -> List[str]:
    caveats: List[str] = []
    if df.empty:
        return [f"No rows were returned from the {label} board."]
    missing_total = int(df.isna().sum().sum())
    if missing_total:
        caveats.append(f"{missing_total} missing values were present across the {label} board.")
    if amount_column and amount_column in df.columns:
        missing_amount = int(pd.to_numeric(df[amount_column], errors="coerce").isna().sum())
        if missing_amount:
            caveats.append(f"{missing_amount} records were omitted from amount-based metrics because {amount_column} was missing or unparseable.")
    if status_column and status_column in df.columns:
        missing_status = int(df[status_column].isna().sum())
        if missing_status:
            caveats.append(f"{missing_status} records were omitted from status-based metrics because {status_column} was missing.")
    if date_column and date_column in df.columns:
        missing_dates = int(pd.to_datetime(df[date_column], errors="coerce").isna().sum())
        if missing_dates:
            caveats.append(f"{missing_dates} records were omitted from date-based metrics because {date_column} could not be parsed.")
    return caveats or ["No major data quality issues were detected."]


def _top_summary(df: pd.DataFrame, category_column: Optional[str], amount_column: Optional[str] = None, top_n: int = 5) -> List[Dict[str, Any]]:
    if not category_column or category_column not in df.columns:
        return []
    working = df[[category_column]].copy()
    working[category_column] = working[category_column].map(_safe_text)
    working = working[working[category_column].notna()]
    if working.empty:
        return []
    if amount_column and amount_column in df.columns:
        working["amount"] = pd.to_numeric(df.loc[working.index, amount_column], errors="coerce").fillna(0)
        grouped = working.groupby(category_column).agg(count=(category_column, "size"), total=("amount", "sum")).reset_index()
        grouped = grouped.sort_values(["total", "count"], ascending=[False, False])
        return grouped.head(top_n).rename(columns={category_column: "label"}).to_dict("records")
    grouped = working.groupby(category_column).size().reset_index(name="count").sort_values("count", ascending=False)
    return grouped.head(top_n).rename(columns={category_column: "label"}).to_dict("records")


def _flatten_board(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "column_values" not in df.columns:
        return df.copy()
    rows: List[Dict[str, Any]] = []
    for _, source_row in df.iterrows():
        row: Dict[str, Any] = {}
        for column in df.columns:
            if column != "column_values":
                value = source_row.get(column)
                if column == "group" and isinstance(value, dict):
                    row["group_id"] = value.get("id")
                    row["group_name"] = value.get("title")
                else:
                    row[column] = value
        column_values = source_row.get("column_values")
        if isinstance(column_values, str):
            try:
                column_values = json.loads(column_values)
            except Exception:
                column_values = []
        for entry in column_values or []:
            if isinstance(entry, dict):
                row[entry.get("id")] = entry.get("text") or entry.get("value")
        rows.append(row)
    return pd.DataFrame(rows)


def get_deals_data(api_token: Optional[str] = None) -> pd.DataFrame:
    return _flatten_board(fetch_board_as_dataframe(DEALS_BOARD_ID, api_token=api_token, normalize=False))


def get_work_orders_data(api_token: Optional[str] = None) -> pd.DataFrame:
    return _flatten_board(fetch_board_as_dataframe(WORK_ORDERS_BOARD_ID, api_token=api_token, normalize=False))


def summarize_deals_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    amount_column = _find_column(df, ["deal value", "revenue", "amount", "value", "contract value", "price", "total"]) or next((c for c in df.columns if pd.api.types.is_numeric_dtype(pd.to_numeric(df[c], errors="coerce")) and c not in {"id", "item_id"}), None)
    stage_column = _find_column(df, ["stage", "status", "phase", "pipeline phase"])
    sector_column = _find_column(df, ["sector", "industry", "vertical", "segment"])
    owner_column = _find_column(df, ["owner", "salesperson", "rep", "assignee"])
    date_column = _find_column(df, ["close date", "expected close", "closing date", "created", "updated", "date"])
    amount_series = pd.to_numeric(df[amount_column], errors="coerce") if amount_column and amount_column in df.columns else None
    stage_series = df[stage_column].map(_safe_text) if stage_column and stage_column in df.columns else None
    stage_breakdown = _top_summary(df, stage_column, amount_column, 8)
    sector_breakdown = _top_summary(df, sector_column, amount_column, 5)
    owner_breakdown = _top_summary(df, owner_column, amount_column, 5)
    pipeline_total = float(amount_series.fillna(0).sum()) if amount_series is not None else None
    open_pipeline = None
    open_deals_count = None
    closed_won = closed_lost = None
    if amount_series is not None and stage_series is not None:
        lower = stage_series.fillna("").str.lower()
        open_mask = ~lower.str.contains(r"won|lost|closed|done|complete|cancel", regex=True, na=False)
        open_pipeline = float(amount_series[open_mask].fillna(0).sum())
        open_deals_count = int(open_mask.sum())
        closed_won = float(amount_series[lower.str.contains("won", na=False)].fillna(0).sum())
        closed_lost = float(amount_series[lower.str.contains("lost", na=False)].fillna(0).sum())
    elif amount_series is not None:
        open_pipeline = pipeline_total
        open_deals_count = int(amount_series.notna().sum())
    return {
        "board": "Deals",
        "row_count": int(df.shape[0]),
        "column_count": int(df.shape[1]),
        "inferred_columns": {"amount": amount_column, "stage": stage_column, "sector": sector_column, "owner": owner_column, "date": date_column},
        "key_metrics": {"pipeline_total": pipeline_total, "open_pipeline": open_pipeline, "closed_won_pipeline": closed_won, "closed_lost_pipeline": closed_lost, "open_deals_count": open_deals_count, "missing_amount_count": int(amount_series.isna().sum()) if amount_series is not None else None, "missing_stage_count": int(stage_series.isna().sum()) if stage_series is not None else None},
        "stage_breakdown": stage_breakdown,
        "sector_breakdown": sector_breakdown,
        "owner_breakdown": owner_breakdown,
        "recent_preview": df[[c for c in ["item_name", owner_column, sector_column, stage_column, amount_column, date_column] if c and c in df.columns]].head(5).to_dict("records") if any(c and c in df.columns for c in ["item_name", owner_column, sector_column, stage_column, amount_column, date_column]) else [],
        "caveats": _quality_caveats(df, amount_column, stage_column, date_column, "Deals"),
    }


def summarize_work_orders_dataframe(df: pd.DataFrame) -> Dict[str, Any]:
    status_column = _find_column(df, ["status", "stage", "progress", "state"])
    assignee_column = _find_column(df, ["assignee", "owner", "assigned to", "responsible", "person"])
    priority_column = _find_column(df, ["priority", "severity", "urgency", "importance"])
    due_date_column = _find_column(df, ["due date", "deadline", "due", "target date", "delivery date"])
    updated_column = _find_column(df, ["updated", "updated at", "last updated", "modified", "last modified"])
    status_series = df[status_column].map(_safe_text) if status_column and status_column in df.columns else None
    due_series = _to_datetime(df[due_date_column]) if due_date_column and due_date_column in df.columns else None
    updated_series = _to_datetime(df[updated_column]) if updated_column and updated_column in df.columns else None
    today = pd.Timestamp.utcnow().normalize()
    open_count = blocked_count = overdue_count = stale_count = None
    if status_series is not None:
        status_lower = status_series.fillna("").str.lower()
        open_mask = ~status_lower.str.contains(r"done|complete|closed|resolved|cancel|shipped", regex=True, na=False)
        open_count = int(open_mask.sum())
        blocked_count = int(status_lower.str.contains(r"blocked|hold|stuck|waiting", regex=True, na=False).sum())
    else:
        open_mask = pd.Series([True] * len(df), index=df.index)
    if due_series is not None:
        overdue_count = int((due_series.notna() & (due_series.dt.normalize() < today) & open_mask).sum())
    if updated_series is not None:
        stale_count = int((updated_series.notna() & ((today - updated_series.dt.normalize()).dt.days.ge(14)) & open_mask).sum())
    return {
        "board": "Work Orders",
        "row_count": int(df.shape[0]),
        "column_count": int(df.shape[1]),
        "inferred_columns": {"status": status_column, "assignee": assignee_column, "priority": priority_column, "due_date": due_date_column, "updated": updated_column},
        "key_metrics": {"open_count": open_count, "blocked_count": blocked_count, "overdue_count": overdue_count, "stale_count": stale_count},
        "status_breakdown": _top_summary(df, status_column, top_n=8),
        "assignee_breakdown": _top_summary(df, assignee_column, top_n=5),
        "priority_breakdown": _top_summary(df, priority_column, top_n=5),
        "recent_preview": df[[c for c in ["item_name", assignee_column, priority_column, status_column, due_date_column, updated_column] if c and c in df.columns]].head(5).to_dict("records") if any(c and c in df.columns for c in ["item_name", assignee_column, priority_column, status_column, due_date_column, updated_column]) else [],
        "caveats": _quality_caveats(df, None, status_column, due_date_column or updated_column, "Work Orders"),
    }


def _build_leadership_markdown(deals: Dict[str, Any], work_orders: Dict[str, Any]) -> str:
    d = deals.get("key_metrics", {})
    w = work_orders.get("key_metrics", {})
    caveats: List[str] = []
    for item in (deals.get("caveats", []) or []) + (work_orders.get("caveats", []) or []):
        if item and item not in caveats:
            caveats.append(item)
    stage_rows = deals.get("stage_breakdown", [])[:5]
    sector_rows = deals.get("sector_breakdown", [])[:5]
    status_rows = work_orders.get("status_breakdown", [])[:5]
    md = [
        "# Executive Update",
        "",
        "## High-Level Revenue & Pipeline Summary",
        f"- Total pipeline: {_format_currency(d.get('pipeline_total'))}",
        f"- Open pipeline: {_format_currency(d.get('open_pipeline'))} across {_format_number(d.get('open_deals_count'))} open deals",
        f"- Closed won: {_format_currency(d.get('closed_won_pipeline'))}; Closed lost: {_format_currency(d.get('closed_lost_pipeline'))}",
        "",
        "## Key Operational Bottlenecks / Delayed Work Orders",
        f"- Blocked: {_format_number(w.get('blocked_count'))}",
        f"- Overdue: {_format_number(w.get('overdue_count'))}",
        f"- Stale: {_format_number(w.get('stale_count'))}",
        "",
        "## Sector Performance Breakdown",
    ]
    if sector_rows:
        md.append("| Sector | Deals | Revenue |")
        md.append("| --- | --- | --- |")
        for row in sector_rows:
            md.append(f"| {row.get('label', '')} | {_format_number(row.get('count'))} | {_format_currency(row.get('total'))} |")
    else:
        md.append("_No sector data available._")
    md.extend([
        "",
        "## Pipeline Stage Snapshot",
    ])
    if stage_rows:
        md.append("| Stage | Deals | Value |")
        md.append("| --- | --- | --- |")
        for row in stage_rows:
            md.append(f"| {row.get('label', '')} | {_format_number(row.get('count'))} | {_format_currency(row.get('total'))} |")
    else:
        md.append("_No stage data available._")
    md.extend([
        "",
        "## Work Order Status Snapshot",
    ])
    if status_rows:
        md.append("| Status | Items |")
        md.append("| --- | --- |")
        for row in status_rows:
            md.append(f"| {row.get('label', '')} | {_format_number(row.get('count'))} |")
    else:
        md.append("_No work order status data available._")
    md.extend([
        "",
        "## Actionable Executive Takeaways",
        "- Prioritize blocked and overdue work orders first.",
        "- Watch for concentration in the largest revenue sectors.",
        "- Use the stage distribution to spot bottlenecks in the pipeline.",
        "",
        "## Data Quality",
    ])
    md.extend([f"- {item}" for item in caveats] if caveats else ["- No major data quality issues were detected."])
    return "\n".join(md)


def _is_leadership_request(text: str) -> bool:
    lowered = text.lower()
    return any(item in lowered for item in LEADERSHIP_HINTS)


def _clarify(text: str) -> Optional[str]:
    lowered = text.lower().strip()
    if len(lowered.split()) <= 4 and any(word in lowered for word in ("status", "update", "how", "doing", "happening")):
        return "Do you want me to look at Deals, Work Orders, or both?"
    if any(item in lowered for item in AMBIGUOUS_HINTS) and not any(word in lowered for word in ("deal", "deals", "work order", "work orders", "pipeline", "revenue")):
        return "Which board or metric should I focus on?"
    return None


def _build_client(api_key: Optional[str]) -> ChatGoogleGenerativeAI:
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        raise ValueError("Missing GEMINI_API_KEY.")
    return ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest", google_api_key=key, temperature=0)


def _tool_defs() -> List[Dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": "get_deals_data", "description": "Fetch and summarize the Deals board.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
        {"type": "function", "function": {"name": "get_work_orders_data", "description": "Fetch and summarize the Work Orders board.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    ]


def _call_model(messages: List[Dict[str, str]], client: ChatGoogleGenerativeAI, model: str, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    response = client.invoke(messages)
    return response


def _run_tools(tool_calls: Sequence[Any], monday_api_token: Optional[str]) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    for call in tool_calls:
        name = getattr(call.function, "name", None)
        if name == "get_deals_data":
            results[name] = summarize_deals_dataframe(get_deals_data(api_token=monday_api_token))
        elif name == "get_work_orders_data":
            results[name] = summarize_work_orders_dataframe(get_work_orders_data(api_token=monday_api_token))
    return results


def answer_user_message(user_message: str, history: Optional[Sequence[Dict[str, str]]] = None, monday_api_token: Optional[str] = None, gemini_api_key: Optional[str] = None) -> AgentResponse:
    monday_api_token = monday_api_token or os.getenv("MONDAY_API_TOKEN")
    if _is_leadership_request(user_message):
        deals = summarize_deals_dataframe(get_deals_data(api_token=monday_api_token))
        work_orders = summarize_work_orders_dataframe(get_work_orders_data(api_token=monday_api_token))
        return AgentResponse(content=_build_leadership_markdown(deals, work_orders), metadata={"mode": "leadership_update", "deals_summary": deals, "work_orders_summary": work_orders})
    clarification = _clarify(user_message)
    if clarification:
        return AgentResponse(content=clarification, needs_clarification=True, metadata={"mode": "clarification"})
    lower = user_message.lower()
    deals_needed = any(word in lower for word in ("deal", "deals", "pipeline", "revenue", "sector", "sales"))
    work_orders_needed = any(word in lower for word in ("work order", "work orders", "blocked", "overdue", "stale", "operations", "delivery", "project"))
    if not deals_needed and not work_orders_needed:
        deals_needed = work_orders_needed = True

    payloads: List[Dict[str, Any]] = []
    sections: List[str] = []
    if deals_needed:
        deals = summarize_deals_dataframe(get_deals_data(api_token=monday_api_token))
        payloads.append(deals)
        sections.append("Deals summary:\n" + json.dumps(deals, default=str, indent=2))
    if work_orders_needed:
        work_orders = summarize_work_orders_dataframe(get_work_orders_data(api_token=monday_api_token))
        payloads.append(work_orders)
        sections.append("Work orders summary:\n" + json.dumps(work_orders, default=str, indent=2))

    client = _build_client(gemini_api_key)
    prompt = (
        "Answer the user's question using only the provided monday.com summaries. "
        "Be concise, specific, and include the relevant data quality caveats.\n\n"
        f"User question: {user_message}\n\n"
        + "\n\n".join(sections)
    )
    messages: List[Dict[str, str]] = []
    for item in history or []:
        role = (item.get("role") or "").strip().lower()
        content = item.get("content") or ""
        if role in {"user", "assistant"}:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})

    full_prompt = f"{SYSTEM_PROMPT}\n\n" + "\n\n".join(f"[{item['role']}]: {item['content']}" for item in messages)
    response = client.invoke(full_prompt)
    content = response.content if hasattr(response, 'content') else str(response)
    caveats: List[str] = []
    for payload in payloads:
        for item in payload.get("caveats", []) or []:
            if item and item not in caveats:
                caveats.append(item)
    if caveats and "data quality" not in content.lower():
        content = f"{content.rstrip()}\n\n## Data quality caveats\n" + "\n".join(f"- {item}" for item in caveats)
    return AgentResponse(content=content, metadata={"mode": "summary_then_llm", "tool_payloads": payloads})


answer_user_message = answer_user_message
