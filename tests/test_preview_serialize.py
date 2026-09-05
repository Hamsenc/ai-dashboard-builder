"""Test _serialize_value() trong datasource/preview.py — mọi giá trị BigQuery trả
về (date/timestamp/Decimal/bytes/NULL/nested) phải ra JSON-serializable đúng trước
khi trả qua API, không cần credentials/network."""

import sys
import pathlib
import datetime
import decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from datasource.preview import _serialize_value


def test_none_stays_none():
    assert _serialize_value(None) is None


def test_date_isoformat():
    assert _serialize_value(datetime.date(2026, 1, 15)) == "2026-01-15"


def test_datetime_isoformat():
    v = datetime.datetime(2026, 1, 15, 10, 30, 0)
    assert _serialize_value(v) == v.isoformat()


def test_decimal_to_str():
    assert _serialize_value(decimal.Decimal("123.456")) == "123.456"


def test_bytes_to_placeholder():
    assert _serialize_value(b"\x00\x01") == "<binary>"


def test_primitives_pass_through():
    assert _serialize_value(42) == 42
    assert _serialize_value(3.14) == 3.14
    assert _serialize_value("text") == "text"
    assert _serialize_value(True) is True


def test_nested_dict_recurses():
    v = {"date": datetime.date(2026, 1, 1), "amount": decimal.Decimal("10")}
    assert _serialize_value(v) == {"date": "2026-01-01", "amount": "10"}


def test_nested_list_recurses():
    v = [datetime.date(2026, 1, 1), decimal.Decimal("10"), None]
    assert _serialize_value(v) == ["2026-01-01", "10", None]


if __name__ == "__main__":
    from _run import run_tests
    run_tests(globals())
