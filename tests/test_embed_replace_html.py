"""Test thay file HTML giữ nguyên link: event mới cùng embed_id, trỏ file GCS mới, giữ
nguyên mọi field khác. Giả lập store/GCS bằng monkeypatch — không cần network."""

import asyncio
import io
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from api import embeds
from fastapi import HTTPException, UploadFile

OLD = {"embed_id": "e1", "title": "BST", "gcs_path": "embeds/e1.html", "data_query_spec": {"specs": {}},
       "data_table_id": "t", "owner_name": "A", "prompt_note": None, "data_file_gcs_path": None,
       "data_file_name": None, "group_name": "G", "data_file_columns": None}


def _setup():
    uploads, events = [], []
    embeds.get_bq_client = lambda: None
    embeds.embeds_store.get_active_embed = lambda c, i: dict(OLD)
    embeds._assert_can_edit = lambda c, e, u: None
    embeds.upload_html = lambda path, html: uploads.append((path, html))
    embeds.embeds_store.insert_embed_event = lambda c, i, ev, **kw: events.append((i, ev, kw))
    return uploads, events


def test_replace_keeps_link_and_fields():
    uploads, events = _setup()
    f = UploadFile(io.BytesIO("<html>mới</html>".encode()), filename="v2.html")
    out = asyncio.run(embeds.replace_embed_html("e1", f, user="a@x"))
    assert out["view_url"] == "/d/e1"
    path, html = uploads[0]
    assert path.startswith("embeds/e1_") and path != OLD["gcs_path"] and html == "<html>mới</html>"
    embed_id, ev, kw = events[0]
    assert (embed_id, ev, kw["gcs_path"]) == ("e1", "updated", path)
    assert kw["data_query_spec"] == OLD["data_query_spec"] and kw["group_name"] == "G" and kw["title"] == "BST"


def test_replace_rejects_non_html():
    _setup()
    f = UploadFile(io.BytesIO(b"x"), filename="v2.txt")
    try:
        asyncio.run(embeds.replace_embed_html("e1", f, user="a@x"))
        raise AssertionError("phải từ chối file không phải .html")
    except HTTPException as e:
        assert e.status_code == 400


if __name__ == "__main__":
    from _run import run_tests
    run_tests(globals())
