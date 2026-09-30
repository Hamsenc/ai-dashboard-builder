"""Test /d/{id}/data chạy các spec song song mà vẫn trả đúng payload {tên: kết quả}.
Giả lập store/BigQuery bằng monkeypatch — không cần credentials/network."""

import sys
import pathlib
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from api import embed_view


def test_multi_spec_runs_in_parallel():
    names = ["ty", "hr", "ly"]
    running, peak, lock = [0], [0], threading.Lock()

    def fake_run_plan(client, plan):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.2)
        with lock:
            running[0] -= 1
        return {"columns": ["x"], "rows": [{"x": plan}]}

    embed_view.get_bq_client = lambda: None
    embed_view.embeds_store.get_active_embed = lambda c, i: {"data_query_spec": {"specs": {}}}
    embed_view.query_spec.build_queries = lambda c, s: {n: n for n in names}
    embed_view._run_plan = fake_run_plan
    embed_view.invalidate_cache("e1")

    t0 = time.time()
    payload = embed_view.get_embed_data("e1")
    assert time.time() - t0 < 0.5, "3 query phải chạy song song"
    assert peak[0] == 3
    assert payload == {n: {"columns": ["x"], "rows": [{"x": n}]} for n in names}


if __name__ == "__main__":
    from _run import run_tests
    run_tests(globals())
