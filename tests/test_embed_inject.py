"""Test toolbar chèn vào </body> CUỐI CÙNG — HTML nhúng thẳng ECharts có chuỗi
'<body ...></body>' trong code, chèn vào chỗ đầu tiên làm vỡ <script> thư viện."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from api.embed_view import _inject_toolbar

EMBED = {"data_query_spec": {"table_id": "x"}}


def test_toolbar_goes_before_last_body_close():
    lib = "<script>var _='<body style=\"margin:0;\"><img/></body>';</script>"
    html = f"<html><head></head><body>{lib}<div>dash</div></body></html>"
    out = _inject_toolbar(html, "e1", EMBED)
    assert lib in out, "code thư viện phải còn nguyên"
    assert out.index("__ldbToolbar") > out.index("<div>dash</div>")
    assert out.endswith("</body></html>")


def test_no_body_close_appends():
    assert _inject_toolbar("<div>x</div>", "e1", EMBED).startswith("<div>x</div>\n<div id=\"__ldbToolbar\"")


if __name__ == "__main__":
    from _run import run_tests
    run_tests(globals())
