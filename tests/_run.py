"""Runner nhỏ dùng chung cho các file test kiểu def test_*() + assert trần (repo
không dùng pytest) — tránh copy-paste vòng lặp thu thập/chạy/in kết quả ở mỗi
file test mới."""

import traceback


def run_tests(test_globals: dict) -> None:
    tests = [v for k, v in test_globals.items() if k.startswith("test_") and callable(v)]
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
