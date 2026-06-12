"""
Track C shareholder analytics agent — governed SQL on bi_* views only.

Uses OpenAI gpt-4o-mini when AGENT_ENABLED and AGENT_LLM_* env vars are set.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

import requests
from django.conf import settings
from django.db import connections, transaction

from analytics.models import AgentQueryAudit

ALLOWED_VIEWS = frozenset({
    "bi_assignments",
    "bi_seasons",
    "bi_last_etl",
    "bi_clients",
    "bi_invoices",
    "bi_return_metrics",
    "bi_return_coverage",
    "bi_return_comparison",
    "bi_return_profile",
})

_FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|"
    r"EXECUTE|CALL|SET|VACUUM|ANALYZE|pg_|information_schema)\b",
    re.IGNORECASE,
)

_VIEW_REF = re.compile(
    r"\b(?:FROM|JOIN)\s+([a-z_][a-z0-9_]*)\b",
    re.IGNORECASE,
)

VIEW_CATALOG = """
Available read-only views (analytics warehouse only):

bi_seasons — tax seasons (tax_season_year, is_active, start_date, end_date)
bi_clients — clients (source_client_id, client_name, filing_type; tin masked in UI)
bi_assignments — one row per product assignment (primary KPI grain):
  tax_season_year, lifecycle_state, payment_method, product_type, filing_type,
  expected_fee, actual_revenue_recognized, revenue_gap, days_to_payment,
  has_parser_snapshot, parser_federal_amount, parser_tax_prep_fee,
  clearing_complete_at, closed_at, tp_comp_date
bi_last_etl — last successful ETL run (finished_at, rows_assignments)
bi_invoices — invoice facts (amount, balance, paid_amount, is_paid, status)
bi_return_metrics, bi_return_coverage, bi_return_comparison, bi_return_profile — NOT deployed yet; do not use.

Rules:
- SELECT only; single statement; always include LIMIT (max 500).
- Prefer aggregates (AVG, COUNT, SUM) over row-level client data.
- Filter by tax_season_year when comparing seasons.
- Do not select tin or other PII columns unless required; mask in summaries.
""".strip()


class AgentError(Exception):
    """User-facing agent failure."""


@dataclass
class AgentResponse:
    answer: str
    sql: str
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    chart: dict[str, Any] | None = None
    coverage_note: str = ""
    etl_as_of: str | None = None
    audit_id: int | None = None


def agent_enabled() -> bool:
    return bool(getattr(settings, "AGENT_ENABLED", False))


def _llm_config() -> dict[str, str]:
    api_key = getattr(settings, "AGENT_LLM_API_KEY", "") or ""
    if not api_key:
        raise AgentError("Analytics agent is not configured (missing API key).")
    return {
        "api_key": api_key,
        "base_url": (getattr(settings, "AGENT_LLM_BASE_URL", "https://api.openai.com/v1") or "").rstrip("/"),
        "model": getattr(settings, "AGENT_LLM_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
    }


def validate_sql(sql: str) -> str:
    text = (sql or "").strip()
    if not text:
        raise AgentError("No SQL generated.")
    if ";" in text.rstrip(";"):
        raise AgentError("Multiple SQL statements are not allowed.")
    text = text.rstrip(";").strip()
    if not re.match(r"^SELECT\b", text, re.IGNORECASE):
        raise AgentError("Only SELECT queries are allowed.")
    if _FORBIDDEN_SQL.search(text):
        raise AgentError("Query contains forbidden keywords.")
    refs = {m.group(1).lower() for m in _VIEW_REF.finditer(text)}
    unknown = refs - ALLOWED_VIEWS
    if unknown:
        raise AgentError(f"Query references disallowed relations: {', '.join(sorted(unknown))}")
    if not refs:
        raise AgentError("Query must read from an allowed bi_* view.")
    if not re.search(r"\bLIMIT\s+\d+", text, re.IGNORECASE):
        text = f"{text}\nLIMIT 100"
    limit_match = re.search(r"\bLIMIT\s+(\d+)", text, re.IGNORECASE)
    if limit_match and int(limit_match.group(1)) > 500:
        raise AgentError("LIMIT must be 500 or less.")
    return text


def execute_agent_sql(sql: str) -> tuple[list[str], list[list[Any]]]:
    validated = validate_sql(sql)
    conn = connections["analytics"]
    try:
        with conn.cursor() as cursor:
            cursor.execute(validated)
            columns = [col[0] for col in cursor.description] if cursor.description else []
            rows = [list(r) for r in cursor.fetchall()]
    except Exception as exc:
        raise AgentError(f"Warehouse query failed: {exc}") from exc
    return columns, rows


def _extract_completion_text(data: dict[str, Any]) -> str:
    try:
        choice = data["choices"][0]
        message = choice.get("message") or {}
        content = message.get("content")
        if content is None:
            refusal = message.get("refusal")
            if refusal:
                raise AgentError(f"LLM refused the request: {refusal}")
            raise AgentError(
                "LLM returned an empty response. Check model name and API key, then retry."
            )
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text") or ""))
            content = "".join(parts)
        text = str(content).strip()
        if not text:
            raise AgentError("LLM returned an empty response.")
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length":
            raise AgentError(
                "LLM response was truncated. Try a simpler question or shorter season filter."
            )
        return text
    except (KeyError, IndexError, TypeError) as exc:
        raise AgentError(
            "Unexpected LLM response format. Verify AGENT_LLM_MODEL (e.g. gpt-4o-mini)."
        ) from exc


def _call_openai(
    *,
    messages: list[dict[str, str]],
    temperature: float = 0.1,
    json_mode: bool = False,
    max_tokens: int = 1024,
) -> str:
    cfg = _llm_config()
    url = f"{cfg['base_url']}/chat/completions"
    payload: dict[str, Any] = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {cfg['api_key']}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=int(getattr(settings, "AGENT_LLM_TIMEOUT_SECONDS", 60)),
        )
        if not resp.ok:
            detail = resp.text[:300].strip()
            raise AgentError(
                f"OpenAI API error ({resp.status_code}): {detail or resp.reason}"
            )
        data = resp.json()
    except AgentError:
        raise
    except requests.RequestException as exc:
        raise AgentError(f"LLM request failed: {exc}") from exc
    except ValueError as exc:
        raise AgentError("OpenAI returned a non-JSON HTTP body.") from exc

    return _extract_completion_text(data)


def _parse_json_block(text: str) -> dict[str, Any]:
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    parsed: Any = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(raw[start:end + 1])
            except json.JSONDecodeError as exc:
                raise AgentError(
                    "LLM did not return valid JSON. Try rephrasing or ask a simpler KPI question."
                ) from exc
        else:
            raise AgentError(
                "LLM did not return valid JSON. Try rephrasing or ask a simpler KPI question."
            )
    if not isinstance(parsed, dict):
        raise AgentError("LLM JSON must be an object.")
    return parsed


def generate_sql(question: str) -> str:
    system = (
        "You are a SQL analyst for a tax practice analytics warehouse. "
        "Respond with a single JSON object only: {\"sql\": \"SELECT ...\"}. "
        "Use only bi_assignments, bi_seasons, bi_clients, bi_invoices, bi_last_etl. "
        f"{VIEW_CATALOG}"
    )
    content = _call_openai(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": question},
        ],
        json_mode=True,
        max_tokens=1024,
    )
    payload = _parse_json_block(content)
    sql = payload.get("sql") or ""
    return validate_sql(str(sql))


def summarize_results(
    *,
    question: str,
    sql: str,
    columns: list[str],
    rows: list[list[Any]],
) -> tuple[str, dict[str, Any] | None]:
    preview_rows = rows[:20]
    system = (
        "Summarize query results for a shareholder. Be concise. "
        "Respond with a single JSON object only: "
        "{\"answer\": \"...\", \"chart\": null or "
        "{\"type\": \"bar|line|pie\", \"label_column\": \"...\", "
        "\"value_column\": \"...\", \"title\": \"...\"}}. "
        "Use chart only when a simple visual helps; otherwise chart must be null."
    )
    user_payload = {
        "question": question,
        "sql": sql,
        "columns": columns,
        "rows": preview_rows,
        "row_count": len(rows),
    }
    content = _call_openai(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, default=str)},
        ],
        json_mode=True,
        max_tokens=2048,
    )
    payload = _parse_json_block(content)
    answer = str(payload.get("answer") or "").strip()
    chart = payload.get("chart")
    if chart is not None and not isinstance(chart, dict):
        chart = None
    return answer or "No summary generated.", chart


def _coverage_note() -> str:
    columns: list[str] = []
    rows: list[list[Any]] = []
    for sql in (
        "SELECT parsed_returns, total_assignments FROM bi_return_coverage "
        "ORDER BY tax_season_year DESC LIMIT 1",
        "SELECT "
        "SUM(CASE WHEN has_parser_snapshot THEN 1 ELSE 0 END) AS parsed_returns, "
        "COUNT(*) AS total_assignments "
        "FROM bi_assignments WHERE is_active = true LIMIT 1",
    ):
        try:
            with transaction.atomic(using="analytics"):
                columns, rows = execute_agent_sql(sql)
            break
        except Exception:
            continue
    if not rows:
        return ""
    idx = {name: i for i, name in enumerate(columns)}
    parsed = rows[0][idx.get("parsed_returns", 0)]
    total = rows[0][idx.get("total_assignments", 1)]
    return f"Metrics based on {parsed} returns with parsed data of {total} total assignments."


def _etl_as_of() -> str | None:
    try:
        with transaction.atomic(using="analytics"):
            _, rows = execute_agent_sql(
                "SELECT finished_at FROM bi_last_etl LIMIT 1"
            )
    except Exception:
        return None
    if not rows or rows[0][0] is None:
        return None
    return str(rows[0][0])


def _audit_query(
    *,
    user,
    question: str,
    sql: str,
    row_count: int,
    status: str,
    error_message: str = "",
) -> int:
    sql_hash = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:64]
    entry = AgentQueryAudit.objects.using("analytics").create(
        user_email=getattr(user, "email", "") or "",
        user_role=getattr(user, "role", "") or "",
        question=question[:2000],
        sql_hash=sql_hash,
        sql_text=sql[:8000],
        row_count=row_count,
        status=status,
        error_message=error_message[:2000],
    )
    return entry.id


def ask_agent(question: str, *, user) -> AgentResponse:
    if not agent_enabled():
        raise AgentError("Analytics agent is disabled.")
    if not (question or "").strip():
        raise AgentError("Question is required.")

    question = question.strip()
    sql = ""
    try:
        sql = generate_sql(question)
        columns, rows = execute_agent_sql(sql)
        answer, chart = summarize_results(
            question=question,
            sql=sql,
            columns=columns,
            rows=rows,
        )
        coverage = _coverage_note()
        etl_as_of = _etl_as_of()
        audit_id = _audit_query(
            user=user,
            question=question,
            sql=sql,
            row_count=len(rows),
            status=AgentQueryAudit.Status.SUCCESS,
        )
        return AgentResponse(
            answer=answer,
            sql=sql,
            columns=columns,
            rows=rows,
            chart=chart,
            coverage_note=coverage,
            etl_as_of=etl_as_of,
            audit_id=audit_id,
        )
    except AgentError as exc:
        _audit_query(
            user=user,
            question=question,
            sql=sql or "(rejected before execution)",
            row_count=0,
            status=AgentQueryAudit.Status.FAILED,
            error_message=str(exc),
        )
        raise
