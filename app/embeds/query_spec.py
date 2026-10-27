"""Validate + build SQL cho query "sống" của 1 dashboard embed, từ 1 spec JSON có
cấu trúc — KHÔNG bao giờ nhận SQL tự do từ client. Đây là endpoint PUBLIC
(app/api/embed_view.py, không cần đăng nhập để gọi), nên mọi identifier (tên
bảng/cột) phải đối chiếu với ground-truth thật từ bq_meta trước khi được ghép vào
chuỗi SQL — cùng triết lý sanitize_turn() ở app/advisor/service.py.

Lưu ý bảo mật quan trọng: KHÔNG chỉ validate `columns` rồi tin các field khác —
BigQuery hỗ trợ multi-statement script trong 1 query job, nên MỌI field có thể
mang tên cột (columns, aggregations[].column, filters[].column,
order_by[].column, joins[].on[]) đều phải đối chiếu với cột thật, bảng JOIN cũng
phải qua assert_in_scope, và op/fn/direction/type phải map qua dict cố định phía
server (validate-rồi-map, không bao giờ nhét thẳng chuỗi client gửi vào SQL dù đã
"hợp lệ"). Giá trị lọc (kể cả tham số người xem truyền qua URL) luôn đi bằng query
parameter, không bao giờ ghép chuỗi."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field
from typing import Any

from config import Config
from datasource import bq_meta
from google.cloud import bigquery

_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_AGG_FN = {
    "SUM": "SUM({})", "COUNT": "COUNT({})", "COUNT_DISTINCT": "COUNT(DISTINCT {})",
    "AVG": "AVG({})", "MIN": "MIN({})", "MAX": "MAX({})",
}
_FILTER_OP = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "in": "IN"}
_ORDER_DIR = {"asc": "ASC", "desc": "DESC"}
_FILTER_TYPES = {"STRING", "INT64", "FLOAT64", "BOOL", "DATE", "TIMESTAMP"}
_JOIN_TYPE = {"left": "LEFT JOIN", "inner": "INNER JOIN"}
_BASE_ALIAS = "t"  # alias của bảng chính trong SQL dựng ra; cột bảng JOIN viết "alias.cột"

_DEFAULT_LIMIT = 500


class InvalidQuerySpecError(ValueError):
    """Spec JSON sai cấu trúc, hoặc tham chiếu cột/bảng không tồn tại — lỗi 400,
    khác OutOfScopeError (403) của bq_meta khi table_id ngoài phạm vi Serving."""


@dataclass
class QueryPlan:
    table_id: str
    sql: str
    query_parameters: list[Any] = field(default_factory=list)
    limit: int = _DEFAULT_LIMIT


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise InvalidQuerySpecError(message)


def _table_columns(client: bigquery.Client, table_id: Any) -> dict[str, str]:
    _require(isinstance(table_id, str) and table_id, "Thiếu table_id trong data_query_spec.")
    bq_meta.assert_in_scope(table_id)  # có thể raise OutOfScopeError — để nguyên, không bắt ở đây
    table_meta = bq_meta.get_table(client, table_id)
    _require(table_meta is not None, f"Không tìm thấy bảng '{table_id}' trong phạm vi Serving.")
    return {c["name"]: c.get("type", "STRING") for c in table_meta.get("columns", [])}


def _coerce(value: Any, bq_type: str) -> Any:
    """Ép giá trị lọc về đúng kiểu trước khi thành query parameter — giá trị từ URL
    (tham số người xem truyền lúc mở dashboard) luôn là chuỗi, sai kiểu phải báo 400
    ở đây thay vì để BigQuery ném lỗi 500 khó hiểu."""
    try:
        if bq_type == "INT64":
            return int(value)
        if bq_type == "FLOAT64":
            return float(value)
        if bq_type == "BOOL":
            if isinstance(value, bool):
                return value
            return {"true": True, "1": True, "false": False, "0": False}[str(value).lower()]
        if bq_type == "DATE":
            return datetime.date.fromisoformat(str(value))
        if bq_type == "TIMESTAMP":
            return datetime.datetime.fromisoformat(str(value))
        return str(value)
    except (TypeError, ValueError, KeyError) as e:
        raise InvalidQuerySpecError(f"Giá trị lọc {value!r} không đúng kiểu {bq_type}.") from e


def build_query(
    client: bigquery.Client, spec: dict[str, Any], params: dict[str, list[str]] | None = None
) -> QueryPlan:
    """Validate spec + build SQL. Raises bq_meta.OutOfScopeError (403) nếu
    table_id ngoài SERVING_DATASETS, InvalidQuerySpecError (400) nếu spec sai.

    `params`: tham số người xem truyền qua URL (/d/{id}/data?tên=giá_trị) — chỉ
    dùng cho filter có khai báo "param"; None = lúc validate upload (bỏ qua)."""
    _require(isinstance(spec, dict), "data_query_spec phải là 1 object JSON.")

    table_id = spec.get("table_id")
    tables = {_BASE_ALIAS: _table_columns(client, table_id)}

    def _column(ref: Any, where: str) -> tuple[str, str, str]:
        """"cột" (bảng chính) hoặc "alias.cột" (bảng JOIN) -> (biểu thức SQL, tên cột
        kết quả, kiểu BigQuery). Tên kết quả của cột bảng JOIN là "alias_cột"."""
        _require(isinstance(ref, str), f"Cột {ref!r} không hợp lệ ({where}).")
        alias, _, name = ref.rpartition(".")
        alias = alias or _BASE_ALIAS
        cols = tables.get(alias)
        _require(cols is not None and name in cols, f"Cột '{ref}' không tồn tại ({where}).")
        out = name if alias == _BASE_ALIAS else f"{alias}_{name}"
        return f"`{alias}`.`{name}`", out, cols[name]

    from_sql = f"`{table_id}` AS `{_BASE_ALIAS}`"
    joins = spec.get("joins") or []
    _require(isinstance(joins, list), "joins phải là 1 danh sách.")
    for j in joins:
        _require(isinstance(j, dict), "Mỗi join phải là 1 object.")
        j_alias = j.get("as")
        _require(
            isinstance(j_alias, str) and _ALIAS_RE.match(j_alias) and j_alias not in tables,
            f"joins[].as không hợp lệ hoặc trùng: {j_alias!r}.",
        )
        j_type = j.get("type", "left")
        _require(isinstance(j_type, str) and j_type.lower() in _JOIN_TYPE, f"joins[].type không hợp lệ: {j_type!r}.")
        j_columns = _table_columns(client, j.get("table_id"))
        on = j.get("on")
        _require(isinstance(on, list) and on, "joins[].on phải là danh sách không rỗng [{left, right}].")
        conds = []
        for cond in on:
            _require(isinstance(cond, dict), "Mỗi joins[].on phải là 1 object {left, right}.")
            left_sql, _, _ = _column(cond.get("left"), "joins[].on[].left")  # bảng chính/JOIN trước đó
            right = cond.get("right")
            _require(isinstance(right, str) and right in j_columns, f"Cột '{right}' không tồn tại ({j_alias}, joins[].on[].right).")
            conds.append(f"{left_sql} = `{j_alias}`.`{right}`")
        tables[j_alias] = j_columns
        from_sql += f" {_JOIN_TYPE[j_type.lower()]} `{j['table_id']}` AS `{j_alias}` ON " + " AND ".join(conds)

    columns = spec.get("columns") or []
    _require(isinstance(columns, list), "columns phải là 1 danh sách tên cột.")
    known_aliases: set[str] = set()
    select_parts: list[str] = []
    group_parts: list[str] = []
    for c in columns:
        expr, out, _ = _column(c, "columns")
        _require(out not in known_aliases, f"Cột kết quả bị trùng tên: {out!r}.")
        known_aliases.add(out)
        select_parts.append(f"{expr} AS `{out}`")
        group_parts.append(expr)

    aggregations = spec.get("aggregations") or []
    _require(isinstance(aggregations, list), "aggregations phải là 1 danh sách.")
    for agg in aggregations:
        _require(isinstance(agg, dict), "Mỗi aggregation phải là 1 object.")
        agg_expr, _, _ = _column(agg.get("column"), "aggregations[].column")
        fn = agg.get("fn")
        _require(isinstance(fn, str) and fn.upper() in _AGG_FN, f"aggregations[].fn không hợp lệ: {fn!r}.")
        alias = agg.get("alias")
        _require(
            isinstance(alias, str) and _ALIAS_RE.match(alias) and alias not in known_aliases,
            f"aggregations[].alias không hợp lệ hoặc trùng tên: {alias!r}.",
        )
        known_aliases.add(alias)
        select_parts.append(f"{_AGG_FN[fn.upper()].format(agg_expr)} AS `{alias}`")

    _require(select_parts, "Spec cần ít nhất 1 cột trong columns hoặc aggregations.")

    query_parameters: list[Any] = []
    filters = spec.get("filters") or []
    _require(isinstance(filters, list), "filters phải là 1 danh sách.")
    where_parts: list[str] = []
    for i, f in enumerate(filters):
        _require(isinstance(f, dict), "Mỗi filter phải là 1 object.")
        f_expr, _, _ = _column(f.get("column"), "filters[].column")
        op = f.get("op")
        _require(isinstance(op, str) and op.lower() in _FILTER_OP, f"filters[].op không hợp lệ: {op!r}.")
        op = op.lower()
        f_type = f.get("type", "STRING")
        _require(isinstance(f_type, str) and f_type.upper() in _FILTER_TYPES, f"filters[].type không hợp lệ: {f_type!r}.")
        f_type = f_type.upper()
        param = f.get("param")
        _require(param is None or (isinstance(param, str) and _ALIAS_RE.match(param)), f"filters[].param không hợp lệ: {param!r}.")

        # Ưu tiên: tham số URL -> value mặc định trong spec -> bỏ điều kiện (chỉ khi có param).
        # Truyền tham số rỗng (?brand=) = chủ động bỏ lọc, kể cả khi spec có value mặc định.
        if param and params is not None and param in params:
            values = [v for v in params[param] if v != ""]
            if not values:
                continue
            value: Any = values if op == "in" else values[0]
        elif "value" in f:
            value = f["value"]
        elif param:
            continue
        else:
            raise InvalidQuerySpecError("filters[] thiếu value (hoặc khai báo param để người xem tự truyền).")

        param_name = f"embed_filter_{i}"
        if op == "in":
            _require(isinstance(value, list) and value, "filters[].value của op 'in' phải là danh sách không rỗng.")
            query_parameters.append(bigquery.ArrayQueryParameter(param_name, f_type, [_coerce(v, f_type) for v in value]))
            where_parts.append(f"{f_expr} IN UNNEST(@{param_name})")
        else:
            _require(not isinstance(value, (list, dict)), f"filters[].value của op '{op}' phải là 1 giá trị đơn.")
            query_parameters.append(bigquery.ScalarQueryParameter(param_name, f_type, _coerce(value, f_type)))
            where_parts.append(f"{f_expr} {_FILTER_OP[op]} @{param_name}")

    order_by = spec.get("order_by") or []
    _require(isinstance(order_by, list), "order_by phải là 1 danh sách.")
    order_parts: list[str] = []
    for o in order_by:
        _require(isinstance(o, dict), "Mỗi order_by phải là 1 object.")
        o_column = o.get("column")
        # Chấp nhận cả "alias.cột" lẫn tên kết quả "alias_cột" cho cột bảng JOIN.
        o_column = o_column.replace(".", "_") if isinstance(o_column, str) else o_column
        _require(isinstance(o_column, str) and o_column in known_aliases, f"order_by[].column không hợp lệ: {o.get('column')!r}.")
        direction = o.get("direction", "asc")
        _require(isinstance(direction, str) and direction.lower() in _ORDER_DIR, f"order_by[].direction không hợp lệ: {direction!r}.")
        order_parts.append(f"`{o_column}` {_ORDER_DIR[direction.lower()]}")

    limit = spec.get("limit", _DEFAULT_LIMIT)
    _require(isinstance(limit, int) and not isinstance(limit, bool) and limit > 0, "limit phải là số nguyên dương.")
    limit = min(limit, Config.EMBED_DATA_MAX_ROWS)

    sql = f"SELECT {', '.join(select_parts)} FROM {from_sql}"
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    if aggregations and group_parts:
        sql += " GROUP BY " + ", ".join(group_parts)
    if order_parts:
        sql += " ORDER BY " + ", ".join(order_parts)
    sql += f" LIMIT {limit}"

    _assert_single_select(sql)
    return QueryPlan(table_id=table_id, sql=sql, query_parameters=query_parameters, limit=limit)


def is_multi_spec(spec_dict: dict[str, Any]) -> bool:
    """True nếu spec ở dạng nhiều bảng {"specs": {tên: spec, ...}} thay vì 1 spec
    phẳng cũ (table_id nằm trực tiếp ở top-level) — dùng để phân biệt tường minh
    với embed cũ đã tạo trước khi có tính năng nhiều bảng, không đoán qua shape."""
    return isinstance(spec_dict, dict) and "specs" in spec_dict


def build_queries(
    client: bigquery.Client, spec_dict: dict[str, Any], params: dict[str, list[str]] | None = None
) -> dict[str, QueryPlan]:
    """Validate + build SQL cho spec nhiều bảng {"specs": {tên: spec, ...}}, tối đa
    EMBED_DATA_MAX_SPECS bảng/embed, tổng limit mọi bảng <= EMBED_DATA_MAX_ROWS (giữ
    RAM/payload của 1 lần mở dashboard trong tầm kiểm soát). Mỗi spec con validate
    độc lập y hệt build_query(), dùng chung bộ `params` từ URL."""
    _require(isinstance(spec_dict, dict), "data_query_spec phải là 1 object JSON.")
    specs = spec_dict.get("specs")
    _require(isinstance(specs, dict) and len(specs) > 0, "specs phải là 1 object không rỗng dạng {tên: spec}.")
    _require(len(specs) <= Config.EMBED_DATA_MAX_SPECS, f"Tối đa {Config.EMBED_DATA_MAX_SPECS} bảng dữ liệu sống cho 1 dashboard.")
    plans: dict[str, QueryPlan] = {}
    for name, sub_spec in specs.items():
        _require(
            isinstance(name, str) and _ALIAS_RE.match(name),
            f"Tên dataset '{name}' không hợp lệ — chỉ chữ/số/gạch dưới, không bắt đầu bằng số.",
        )
        plans[name] = build_query(client, sub_spec, params)
    total = sum(p.limit for p in plans.values())
    _require(
        total <= Config.EMBED_DATA_MAX_ROWS,
        f"Tổng limit các bảng là {total:,}, vượt mức tối đa {Config.EMBED_DATA_MAX_ROWS:,} dòng cho 1 dashboard.",
    )
    return plans


def declared_params(spec_dict: dict[str, Any]) -> set[str]:
    """Tên các tham số URL mà spec (1 hay nhiều bảng) khai báo qua filters[].param —
    embed_view chỉ đọc đúng các tham số này từ URL và dùng làm khoá cache, để tham số
    rác không phá cache."""
    specs = spec_dict.get("specs") if is_multi_spec(spec_dict) else {"": spec_dict}
    if not isinstance(specs, dict):
        return set()
    return {
        f["param"]
        for s in specs.values() if isinstance(s, dict) and isinstance(s.get("filters"), list)
        for f in s["filters"] if isinstance(f, dict) and isinstance(f.get("param"), str)
    }


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
