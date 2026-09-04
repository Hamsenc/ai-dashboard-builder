"""Blueprint đã duyệt -> SQL thật, đi qua validator, retry có giới hạn nếu bị chặn.

KHÔNG bao giờ trả SQL chưa qua validator cho execution/bq_client.py — dù retry hết
lượt vẫn còn lỗi thì raise, không âm thầm hạ chuẩn hay bỏ qua KPI lỗi."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from builder.prompts import build_retry_prompt, build_system_prompt
from builder.schema import BUILDER_OUTPUT_SCHEMA, BuilderOutput, QuerySpec
from builder.validator import validate_sql

import llm_client

MAX_RETRIES = 2


class BuildFailedError(RuntimeError):
    def __init__(self, message: str, validator_report: dict):
        super().__init__(message)
        self.validator_report = validator_report


@dataclass
class BuildResult:
    queries: list[QuerySpec]
    default_start_date: str
    default_end_date: str
    validator_report: dict = field(default_factory=dict)
    retry_count: int = 0


async def build(blueprint: dict[str, Any], catalog: dict[str, Any]) -> BuildResult:
    whitelist = [t["table_id"] for t in catalog["tables"]]
    system_prompt = build_system_prompt(catalog)
    blueprint_json = json.dumps(blueprint, ensure_ascii=False, indent=2)

    prompt = f"Blueprint đã duyệt:\n```json\n{blueprint_json}\n```\n\nSinh SQL cho từng KPI."
    last_errors_by_query: dict[str, list[str]] = {}
    last_queries: list[QuerySpec] = []

    for attempt in range(MAX_RETRIES + 1):
        raw = await llm_client.run_structured(system_prompt, prompt, BUILDER_OUTPUT_SCHEMA)
        builder_output = BuilderOutput.model_validate(raw)
        queries = builder_output.queries
        last_queries = queries

        errors_by_query: dict[str, list[str]] = {}
        reports = []
        for q in queries:
            result = validate_sql(q.sql, whitelist)
            reports.append({"kpi_name": q.kpi_name, **result.to_report()})
            if not result.passed:
                errors_by_query[q.kpi_name] = result.errors

        if not errors_by_query:
            return BuildResult(
                queries=queries,
                default_start_date=builder_output.default_start_date.isoformat(),
                default_end_date=builder_output.default_end_date.isoformat(),
                validator_report={"attempt": attempt, "checks": reports},
                retry_count=attempt,
            )

        last_errors_by_query = errors_by_query
        if attempt < MAX_RETRIES:
            # Retry với TOÀN BỘ lỗi của lần trước — đơn giản hơn retry riêng từng KPI,
            # đủ dùng vì Builder thường lặp lại cùng 1 kiểu lỗi (vd quên fully-qualify)
            # trên nhiều KPI cùng lúc.
            all_errors = [f"[{name}] {e}" for name, errs in errors_by_query.items() for e in errs]
            failing_sql = "\n\n".join(
                f"-- {q.kpi_name}\n{q.sql}" for q in queries if q.kpi_name in errors_by_query
            )
            prompt = build_retry_prompt(blueprint_json, failing_sql, all_errors)

    raise BuildFailedError(
        f"Build thất bại sau {MAX_RETRIES + 1} lần thử — vẫn còn lỗi validator ở: "
        f"{list(last_errors_by_query.keys())}",
        validator_report={"final_errors_by_query": last_errors_by_query},
    )
