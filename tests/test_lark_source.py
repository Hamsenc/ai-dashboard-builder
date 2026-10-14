"""Test parse link + chuẩn hoá giá trị ô Lark Base (fixture lấy từ response thật
của bảng 'DỮ LIỆU NGÀY') — không gọi mạng."""

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from _run import run_tests
from embeds import lark_source as ls


def test_parse_url():
    url = "https://o4pvcegwn6b.sg.larksuite.com/base/ANwJb533gaQVrOsVFGIlZKj4gfc?table=tbl1P7RyTxWDke9k&view=vewqcGLsYJ"
    assert ls.parse_url(url) == ("ANwJb533gaQVrOsVFGIlZKj4gfc", "tbl1P7RyTxWDke9k", "vewqcGLsYJ")
    assert ls.parse_url(url.split("&")[0])[2] is None
    for bad in ["https://x.larksuite.com/wiki/abc?table=tbl1", "https://x.larksuite.com/base/abc"]:
        try:
            ls.parse_url(bad)
            raise AssertionError(bad)
        except ls.LarkSourceError:
            pass


def test_validate_sources_name():
    try:
        ls.validate_sources({"1bad": "https://x/base/a?table=t"})
        raise AssertionError
    except ls.LarkSourceError:
        pass


def test_normalize_cell():
    assert ls.normalize_cell(1790701200000, 5) == "2026-09-30"
    assert ls.normalize_cell("33163", 2) == 33163
    assert ls.normalize_cell(0, 20) == 0
    assert ls.normalize_cell([{"text": "BAG", "type": "text"}], 20) == "BAG"
    assert ls.normalize_cell("Shopee", 3) == "Shopee"
    assert ls.normalize_cell(None, 2) is None
    assert ls.normalize_cell({"type": 2, "value": [12.5]}, 19) == 12.5
    assert ls.normalize_cell([{"name": "An", "id": "ou_1"}, {"name": "Bình"}], 11) == "An, Bình"


if __name__ == "__main__":
    run_tests(globals())
