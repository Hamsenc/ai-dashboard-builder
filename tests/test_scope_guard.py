"""Test assert_in_scope() — ranh giới an toàn thật sự của Data Explorer: mọi
endpoint đọc bảng/preview phải qua đây trước khi chạm BigQuery. Không cần
credentials/network vì assert_in_scope là hàm thuần, không gọi BigQuery."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from datasource.bq_meta import assert_in_scope, OutOfScopeError


def test_table_in_serving_dataset_allowed():
    assert_in_scope("surya-495408.00_serving_sales.vw_business_daily")  # không raise


def test_table_outside_serving_datasets_rejected():
    try:
        assert_in_scope("surya-495408.12_data_agent_log.raw_dashboard_builder_chat_messages")
        assert False, "phải raise OutOfScopeError"
    except OutOfScopeError:
        pass


def test_table_wrong_project_rejected():
    try:
        assert_in_scope("some-other-project.00_serving_sales.vw_business_daily")
        assert False, "phải raise OutOfScopeError"
    except OutOfScopeError:
        pass


def test_malformed_table_id_rejected():
    for bad in ["not-a-valid-id", "surya-495408.00_serving_sales", "a.b.c.d", ""]:
        try:
            assert_in_scope(bad)
            assert False, f"phải raise OutOfScopeError cho {bad!r}"
        except OutOfScopeError:
            pass


def test_dataset_substring_not_allowed():
    # "00_serving_sales_extra" KHÔNG được coi là thuộc "00_serving_sales" — so khớp
    # chính xác tên dataset, không phải substring/prefix.
    try:
        assert_in_scope("surya-495408.00_serving_sales_extra.some_table")
        assert False, "phải raise OutOfScopeError"
    except OutOfScopeError:
        pass


if __name__ == "__main__":
    import traceback

    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    if failed:
        raise SystemExit(1)
