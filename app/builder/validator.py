"""Validator KHÔNG dùng LLM — ranh giới an toàn thật sự giữa SQL do Builder (LLM)
sinh ra và việc thực thi trên BigQuery. Luật "chỉ dùng bảng được cấp quyền" phụ
thuộc vào module này, không phụ thuộc sự tự giác của model.

Đây chỉ là lớp phòng thủ THỨ NHẤT (code, dễ audit/test). Lớp thứ 2 độc lập là IAM:
service account của app chỉ có bigquery.dataViewer đúng 3 dataset Serving — nên dù
validator có bug/bị bypass, BigQuery tự chặn ở tầng quyền, không phải chỉ dựa vào
validator này (xem app/execution/bq_client.py + IAM đã cấp ở Phase 0)."""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

_DML_DDL_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,  # câu lệnh non-SQL-chuẩn (EXECUTE IMMEDIATE, DECLARE, CALL...)
)


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    tables_touched: list[str] = field(default_factory=list)

    def to_report(self) -> dict:
        return {
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "tables_touched": self.tables_touched,
        }


def _validate_single_select(
    statement: exp.Expression, whitelist: set[str], raw_sql: str
) -> tuple[list[str], list[str], list[str]]:
    """Validate 1 statement đã parse. Trả về (errors, warnings, tables_touched)."""
    errors: list[str] = []
    warnings: list[str] = []

    for node in statement.walk():
        node_expr = node[0] if isinstance(node, tuple) else node
        if isinstance(node_expr, _DML_DDL_TYPES):
            errors.append(
                f"Chỉ cho phép SELECT — phát hiện node {type(node_expr).__name__} trong SQL."
            )

    root = statement
    if isinstance(root, exp.Command):
        errors.append(f"Statement không phải SQL chuẩn (Command): {root.sql()[:200]}")
        return errors, warnings, []

    is_select_like = isinstance(root, (exp.Select, exp.Union, exp.Intersect, exp.Except))
    if not is_select_like:
        errors.append(
            f"Root statement phải là SELECT hoặc UNION/INTERSECT/EXCEPT của SELECT — "
            f"nhận được {type(root).__name__}."
        )

    # Tên CTE (WITH x AS (...)) xuất hiện lại dưới dạng exp.Table không có catalog/db khi
    # được FROM tới — đây KHÔNG phải bảng thật, không được đòi fully-qualified/whitelist.
    cte_names = {cte.alias_or_name for cte in statement.find_all(exp.CTE)}

    tables_touched: list[str] = []
    for table in statement.find_all(exp.Table):
        catalog = table.catalog  # project
        db = table.db  # dataset
        name = table.name  # table

        if not catalog and not db and name in cte_names:
            continue  # reference tới CTE trong cùng query, không phải bảng thật

        if not catalog or not db:
            errors.append(
                f"Table reference '{table.sql()}' không ở dạng đầy đủ project.dataset.table — "
                "bắt buộc fully-qualified để validator kiểm whitelist chính xác."
            )
            continue
        full_id = f"{catalog}.{db}.{name}"
        tables_touched.append(full_id)
        if full_id not in whitelist:
            errors.append(f"Bảng '{full_id}' không nằm trong whitelist catalog — bị chặn.")
        elif f"`{full_id}`" not in raw_sql:
            # sqlglot parse được catalog.db.table dù KHÔNG có backtick bọc quanh (dễ
            # tính hơn ngữ pháp thật của BigQuery) — nhưng BigQuery thật SẼ TỪ CHỐI vì
            # dataset bắt đầu bằng số (vd 00_serving_sales) là identifier không hợp lệ
            # nếu thiếu backtick. Bắt lỗi này ở đây (retry được) thay vì để BigQuery từ
            # chối lúc thực thi thật (không retry được, tốn 1 lượt build vô ích) — bug
            # đã gặp thật khi Builder quên backtick trong 1 nhánh UNION ALL.
            errors.append(
                f"Bảng '{full_id}' được dùng nhưng KHÔNG được bọc backtick dạng "
                f"`{full_id}` trong SQL — BigQuery sẽ từ chối vì dataset bắt đầu bằng "
                "số nếu thiếu backtick. Phải viết chính xác `project.dataset.table` "
                "trong 1 cặp backtick duy nhất."
            )

    if any(isinstance(e, exp.Star) for e in statement.find_all(exp.Star)):
        warnings.append("Dùng SELECT * — nên liệt kê cột tường minh để dễ audit (không chặn cứng).")

    return errors, warnings, tables_touched


def validate_sql(sql: str, whitelist_table_ids: list[str]) -> ValidationResult:
    """whitelist_table_ids: danh sách 'project.dataset.table' lấy từ catalog['tables'][*]['table_id']."""
    whitelist = set(whitelist_table_ids)

    try:
        statements = sqlglot.parse(sql, read="bigquery")
    except Exception as e:  # sqlglot ném nhiều loại lỗi parse khác nhau
        return ValidationResult(passed=False, errors=[f"Không parse được SQL: {e}"])

    statements = [s for s in statements if s is not None]
    if len(statements) == 0:
        return ValidationResult(passed=False, errors=["SQL rỗng sau khi parse."])
    if len(statements) > 1:
        return ValidationResult(
            passed=False,
            errors=[f"Chỉ cho phép 1 statement — phát hiện {len(statements)} statement (chặn multi-statement injection)."],
        )

    errors, warnings, tables_touched = _validate_single_select(statements[0], whitelist, sql)
    return ValidationResult(
        passed=(len(errors) == 0),
        errors=errors,
        warnings=warnings,
        tables_touched=sorted(set(tables_touched)),
    )
