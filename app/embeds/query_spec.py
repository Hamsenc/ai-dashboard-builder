"""Validate + build SQL cho query "sống" của 1 dashboard embed, từ 1 spec JSON có
cấu trúc — KHÔNG bao giờ nhận SQL tự do từ client. Đây là endpoint PUBLIC
(app/api/embed_view.py, không cần đăng nhập để gọi), nên mọi identifier (tên
bảng/cột) phải đối chiếu với ground-truth thật từ bq_meta trước khi được ghép vào
chuỗi SQL — cùng triết lý sanitize_turn() ở app/advisor/service.py.

Lưu ý bảo mật quan trọng: KHÔNG chỉ validate `columns` rồi tin các field khác —
BigQuery hỗ trợ multi-statement script trong 1 query job, nên MỌI field có thể
mang tên cột (columns, aggregations[].column, filters[].column,
order_by[].column) đều phải đối chiếu với cột thật, và op/fn/direction phải map
qua dict cố định phía server (validate-rồi-map, không bao giờ nhét thẳng chuỗi
client gửi vào SQL dù đã "hợp lệ")."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from datasource import bq_meta
from google.cloud import bigquery

_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_AGG_FN = {"SUM": "SUM", "COUNT": "COUNT", "AVG": "AVG", "MIN": "MIN", "MAX": "MAX"}
_FILTER_OP = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_ORDER_DIR = {"asc": "ASC", "desc": "DESC"}
_FILTER_TYPES = {"STRING", "INT64", "FLOAT64", "BOOL", "DATE", "TIMESTAMP"}

_DEFAULT_LIMIT = 500
_MAX_LIMIT = 10000
_MAX_SPECS = 3


class InvalidQuerySpecError(ValueError):
    """Spec JSON sai cấu trúc, hoặc tham chiếu cột/bảng không tồn tại — lỗi 400,
    khác OutOfScopeError (403) của bq_meta khi table_id ngoài phạm vi Serving."""


@dataclass
class QueryPlan:
    table_id: str
    sql: str
    query_parameters: list[Any] = field(default_factory=list)


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise InvalidQuerySpecError(message)


def build_query(client: bigquery.Client, spec: dict[str, Any]) -> QueryPlan:
    """Validate spec + build SQL. Raises bq_meta.OutOfScopeError (403) nếu
    table_id ngoài SERVING_DATASETS, InvalidQuerySpecError (400) nếu spec sai."""
    _require(isinstance(spec, dict), "data_query_spec phải là 1 object JSON.")

    table_id = spec.get("table_id")
    _require(isinstance(table_id, str) and table_id, "Thiếu table_id trong data_query_spec.")
    bq_meta.assert_in_scope(table_id)  # có thể raise OutOfScopeError — để nguyên, không bắt ở đây

    table_meta = bq_meta.get_table(client, table_id)
    _require(table_meta is not None, f"Không tìm thấy bảng '{table_id}' trong phạm vi Serving.")
    real_columns = {c["name"]: c.get("type", "STRING") for c in table_meta.get("columns", [])}

    def _check_column(name: Any, where: str) -> str:
        _require(isinstance(name, str) and name in real_columns, f"Cột '{name}' không tồn tại trong '{table_id}' ({where}).")
        return name

    columns = spec.get("columns") or []
    _require(isinstance(columns, list), "columns phải là 1 danh sách tên cột.")
    columns = [_check_column(c, "columns") for c in columns]

    aggregations = spec.get("aggregations") or []
    _require(isinstance(aggregations, list), "aggregations phải là 1 danh sách.")
    known_aliases: set[str] = set(columns)
    agg_select_parts: list[str] = []
    for agg in aggregations:
        _require(isinstance(agg, dict), "Mỗi aggregation phải là 1 object.")
        agg_column = _check_column(agg.get("column"), "aggregations[].column")
        fn = agg.get("fn")
        _require(isinstance(fn, str) and fn.upper() in _AGG_FN, f"aggregations[].fn không hợp lệ: {fn!r}.")
        alias = agg.get("alias")
        _require(
            isinstance(alias, str) and _ALIAS_RE.match(alias) and alias not in known_aliases,
            f"aggregations[].alias không hợp lệ hoặc trùng tên: {alias!r}.",
        )
        known_aliases.add(alias)
        agg_select_parts.append(f"{_AGG_FN[fn.upper()]}(`{agg_column}`) AS `{alias}`")

    _require(columns or agg_select_parts, "Spec cần ít nhất 1 cột trong columns hoặc aggregations.")

    query_parameters: list[bigquery.ScalarQueryParameter] = []
    filters = spec.get("filters") or []
    _require(isinstance(filters, list), "filters phải là 1 danh sách.")
    where_parts: list[str] = []
    for i, f in enumerate(filters):
        _require(isinstance(f, dict), "Mỗi filter phải là 1 object.")
        f_column = _check_column(f.get("column"), "filters[].column")
        op = f.get("op")
        _require(isinstance(op, str) and op.lower() in _FILTER_OP, f"filters[].op không hợp lệ: {op!r}.")
        f_type = f.get("type", "STRING")
        _require(isinstance(f_type, str) and f_type.upper() in _FILTER_TYPES, f"filters[].type không hợp lệ: {f_type!r}.")
        _require("value" in f, "filters[] thiếu value.")
        param_name = f"embed_filter_{i}"
        where_parts.append(f"`{f_column}` {_FILTER_OP[op.lower()]} @{param_name}")
        query_parameters.append(bigquery.ScalarQueryParameter(param_name, f_type.upper(), f["value"]))

    order_by = spec.get("order_by") or []
    _require(isinstance(order_by, list), "order_by phải là 1 danh sách.")
    order_parts: list[str] = []
    for o in order_by:
        _require(isinstance(o, dict), "Mỗi order_by phải là 1 object.")
        o_column = o.get("column")
        _require(isinstance(o_column, str) and o_column in known_aliases, f"order_by[].column không hợp lệ: {o_column!r}.")
        direction = o.get("direction", "asc")
        _require(isinstance(direction, str) and direction.lower() in _ORDER_DIR, f"order_by[].direction không hợp lệ: {direction!r}.")
        order_parts.append(f"`{o_column}` {_ORDER_DIR[direction.lower()]}")

    limit = spec.get("limit", _DEFAULT_LIMIT)
    _require(isinstance(limit, int) and not isinstance(limit, bool) and limit > 0, "limit phải là số nguyên dương.")
    limit = min(limit, _MAX_LIMIT)

    select_clause = ", ".join([f"`{c}`" for c in columns] + agg_select_parts)
    sql = f"SELECT {select_clause} FROM `{table_id}`"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if agg_select_parts and columns:
        sql += " GROUP BY " + ", ".join(f"`{c}`" for c in columns)
    if order_parts:
        sql += " ORDER BY " + ", ".join(order_parts)
    sql += f" LIMIT {limit}"

    _assert_single_select(sql)
    return QueryPlan(table_id=table_id, sql=sql, query_parameters=query_parameters)


def is_multi_spec(spec_dict: dict[str, Any]) -> bool:
    """True nếu spec ở dạng nhiều bảng {"specs": {tên: spec, ...}} thay vì 1 spec
    phẳng cũ (table_id nằm trực tiếp ở top-level) — dùng để phân biệt tường minh
    với embed cũ đã tạo trước khi có tính năng nhiều bảng, không đoán qua shape."""
    return isinstance(spec_dict, dict) and "specs" in spec_dict


def build_queries(client: bigquery.Client, spec_dict: dict[str, Any]) -> dict[str, QueryPlan]:
    """Validate + build SQL cho spec nhiều bảng {"specs": {tên: spec, ...}}, tối đa
    _MAX_SPECS bảng/embed. Mỗi spec con validate độc lập y hệt build_query() (vẫn
    chỉ 1 bảng/spec con) — chỉ khác là 1 embed giờ gom được nhiều spec như vậy."""
    _require(isinstance(spec_dict, dict), "data_query_spec phải là 1 object JSON.")
    specs = spec_dict.get("specs")
    _require(isinstance(specs, dict) and len(specs) > 0, "specs phải là 1 object không rỗng dạng {tên: spec}.")
    _require(len(specs) <= _MAX_SPECS, f"Tối đa {_MAX_SPECS} bảng dữ liệu sống cho 1 dashboard.")
    plans: dict[str, QueryPlan] = {}
    for name, sub_spec in specs.items():
        _require(
            isinstance(name, str) and _ALIAS_RE.match(name),
            f"Tên dataset '{name}' không hợp lệ — chỉ chữ/số/gạch dưới, không bắt đầu bằng số.",
        )
        plans[name] = build_query(client, sub_spec)
    return plans


def _assert_single_select(sql: str) -> None:
    """Phòng thủ thêm 1 lớp độc lập với logic build ở trên: parse lại SQL vừa
    dựng, chắc chắn nó CHỈ là 1 câu SELECT duy nhất — chặn khả năng multi-statement
    script lọt qua nếu logic build ở trên có bug (BigQuery hỗ trợ nhiều câu lệnh
    cách nhau bằng ';' trong cùng 1 query job)."""
    import sqlglot
    from sqlglot import exp

    statements = sqlglot.parse(sql, dialect="bigquery")
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise InvalidQuerySpecError("SQL dựng ra không phải đúng 1 câu SELECT duy nhất — từ chối thực thi.")
