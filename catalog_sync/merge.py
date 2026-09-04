"""Gộp 3 nguồn thành 1 catalog JSON duy nhất mà Planner/Builder đọc:

1. Lark '02. Table Catalog' (đã lọc Layer=Serving ở tầng gọi module này) — caveat
   nghiệp vụ cấp bảng, giữ NGUYÊN VĂN, không tóm tắt.
2. BigQuery INFORMATION_SCHEMA (qua information_schema.py) — cột/kiểu dữ liệu ground-truth.
3. Lark '04. Business Logic - KPI' — công thức + Status (Draft/Active), join theo
   Table_ID (record link) về đúng bảng trong nguồn 1.

KPI có ít nhất 1 bảng nguồn nằm trong whitelist Serving -> vào `kpis`.
KPI không có bảng nguồn nào nằm trong whitelist (vd Marketing/Customer domain
chưa được promote lên Serving) -> vào `out_of_scope_kpis`, kèm lý do — để Planner
trả lời "chưa có sẵn" thay vì im lặng bỏ qua hoặc tự bịa.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from information_schema import ColumnInfo
from lark_client import field_text, linked_record_ids

FIELD_TABLE_ID = "Table_ID"
FIELD_STATUS = "Status"
FIELD_LAYER = "Layer"
FIELD_PURPOSE = "Purpose"
FIELD_PARTITION = "Partition"
FIELD_PII_NOTE = "PII Note"
FIELD_CLUSTER = "Cluster"
FIELD_REFRESH = "Refresh"
FIELD_GRAIN = "Grain"
FIELD_DOMAIN = "Domain"
FIELD_DATASET = "Dataset"

KPI_FIELD_NAME = "Name"
KPI_FIELD_TABLE_ID_LINK = "Table_ID"
KPI_FIELD_FORMULA = "Formula / Rule"
KPI_FIELD_VERSION = "Version"
KPI_FIELD_DOMAIN = "Domain"
KPI_FIELD_EFFECTIVE_FROM = "Effective From"
KPI_FIELD_BUSINESS_DEF = "Business Definition"
KPI_FIELD_INPUT_TABLES = "Input Tables / Columns"
KPI_FIELD_OWNER = "Owner"
KPI_FIELD_GRAIN = "Grain"
KPI_FIELD_STATUS = "Status"
KPI_FIELD_TIME_RULE = "Time Rule"
KPI_FIELD_TYPE = "Type"


@dataclass
class TableEntry:
    table_id: str  # "project.dataset.table" đầy đủ
    record_id: str  # record id trong Lark '02. Table Catalog', dùng để join KPI
    project: str
    dataset: str
    table_name: str
    status: str
    purpose: str
    partition: str
    pii_note: str
    cluster: str
    refresh: str
    grain: str
    domain: str
    columns: list[dict[str, Any]] = field(default_factory=list)
    kpi_names: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d.pop("record_id", None)  # chi tiết nội bộ Lark, không cần lộ ra catalog JSON
        return d


def _split_table_id(table_id: str) -> tuple[str, str, str]:
    parts = table_id.split(".")
    if len(parts) != 3:
        raise ValueError(
            f"Table_ID không đúng dạng project.dataset.table: {table_id!r}"
        )
    return parts[0], parts[1], parts[2]


def parse_table_catalog(
    records: list[dict[str, Any]],
    layer_filter: str = "Serving",
) -> dict[str, TableEntry]:
    """records: raw items từ Lark '02. Table Catalog' (record_id + fields).
    Trả về map record_id -> TableEntry, CHỈ gồm dòng có Layer == layer_filter."""
    result: dict[str, TableEntry] = {}
    for rec in records:
        f = rec["fields"]
        layer = field_text(f.get(FIELD_LAYER))
        if layer != layer_filter:
            continue

        table_id = field_text(f.get(FIELD_TABLE_ID))
        if not table_id:
            continue
        project, dataset, table_name = _split_table_id(table_id)

        result[rec["record_id"]] = TableEntry(
            table_id=table_id,
            record_id=rec["record_id"],
            project=project,
            dataset=dataset,
            table_name=table_name,
            status=field_text(f.get(FIELD_STATUS)),
            purpose=field_text(f.get(FIELD_PURPOSE)),
            partition=field_text(f.get(FIELD_PARTITION)),
            pii_note=field_text(f.get(FIELD_PII_NOTE)),
            cluster=field_text(f.get(FIELD_CLUSTER)),
            refresh=field_text(f.get(FIELD_REFRESH)),
            grain=field_text(f.get(FIELD_GRAIN)),
            domain=field_text(f.get(FIELD_DOMAIN)),
        )
    return result


def attach_columns(
    tables_by_record_id: dict[str, TableEntry],
    info_schema: dict[tuple[str, str], list[ColumnInfo]],
) -> None:
    """Gắn cột thật (từ INFORMATION_SCHEMA) vào từng TableEntry, in-place."""
    for entry in tables_by_record_id.values():
        cols = info_schema.get((entry.dataset, entry.table_name), [])
        entry.columns = [
            {"name": c.name, "type": c.data_type, "nullable": c.is_nullable}
            for c in cols
        ]


def parse_and_link_kpis(
    kpi_records: list[dict[str, Any]],
    tables_by_record_id: dict[str, TableEntry],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """records: raw items từ Lark '04. Business Logic - KPI'.
    Trả về (kpis_in_scope, out_of_scope_kpis). Gắn kpi_names vào TableEntry in-place
    cho các KPI in-scope."""
    in_scope: list[dict[str, Any]] = []
    out_of_scope: list[dict[str, Any]] = []

    for rec in kpi_records:
        f = rec["fields"]
        name = field_text(f.get(KPI_FIELD_NAME))
        status = field_text(f.get(KPI_FIELD_STATUS))

        linked_ids = linked_record_ids(f.get(KPI_FIELD_TABLE_ID_LINK))
        matched_tables = [
            tables_by_record_id[rid].table_id
            for rid in linked_ids
            if rid in tables_by_record_id
        ]

        kpi_dict = {
            "name": name,
            "status": status,
            "formula": field_text(f.get(KPI_FIELD_FORMULA)),
            "business_definition": field_text(f.get(KPI_FIELD_BUSINESS_DEF)),
            "domain": field_text(f.get(KPI_FIELD_DOMAIN)),
            "grain": field_text(f.get(KPI_FIELD_GRAIN)),
            "owner": field_text(f.get(KPI_FIELD_OWNER)),
            "time_rule": field_text(f.get(KPI_FIELD_TIME_RULE)),
            "type": field_text(f.get(KPI_FIELD_TYPE)),
            "version": field_text(f.get(KPI_FIELD_VERSION)),
            "input_tables_columns_raw": field_text(f.get(KPI_FIELD_INPUT_TABLES)),
        }

        if matched_tables:
            kpi_dict["tables"] = matched_tables
            in_scope.append(kpi_dict)
            for rid in linked_ids:
                entry = tables_by_record_id.get(rid)
                if entry and name not in entry.kpi_names:
                    entry.kpi_names.append(name)
        else:
            kpi_dict["reason"] = (
                "Nguồn dữ liệu của KPI này không nằm trong whitelist Layer=Serving "
                "hiện tại (chưa được promote) — KHÔNG được dùng, phải báo user."
            )
            out_of_scope.append(kpi_dict)

    return in_scope, out_of_scope


def build_catalog(
    table_catalog_records: list[dict[str, Any]],
    kpi_records: list[dict[str, Any]],
    info_schema: dict[tuple[str, str], list[ColumnInfo]],
    generated_at: str,
) -> dict[str, Any]:
    tables_by_record_id = parse_table_catalog(table_catalog_records)
    attach_columns(tables_by_record_id, info_schema)
    kpis, out_of_scope_kpis = parse_and_link_kpis(kpi_records, tables_by_record_id)

    return {
        "generated_at": generated_at,
        "tables": [e.to_dict() for e in tables_by_record_id.values()],
        "kpis": kpis,
        "out_of_scope_kpis": out_of_scope_kpis,
    }
