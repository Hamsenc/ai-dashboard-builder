"""Test auth.roles — ranh giới quyền admin/embed. is_super_admin() phải normalize
case/whitespace (nếu không, 1 người thật đăng nhập với email đúng nhưng lệch hoa
thường sẽ bị coi là không phải super admin, dù env đã liệt kê đúng họ). has_role()
phải short-circuit ở super admin TRƯỚC KHI chạm BigQuery — không có credentials
trong môi trường test, nên nếu short-circuit này bị xoá, test sẽ crash khi gọi
get_bq_client()/BigQuery thật, không cần mock gì thêm để phát hiện lỗi."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "app"))

from auth.roles import can_use_embeds, has_role, is_super_admin
from config import Config


def test_super_admin_default_present():
    assert "ngadt@hapas.vn" in Config.SUPER_ADMIN_EMAILS


def test_is_super_admin_case_and_whitespace_insensitive():
    assert is_super_admin("ngadt@hapas.vn")
    assert is_super_admin("  NgaDT@Hapas.VN  ")


def test_is_super_admin_rejects_other_email():
    assert not is_super_admin("random@hapas.vn")


def test_has_role_short_circuits_for_super_admin_without_bigquery():
    # Không có GCP credentials nào ở đây — nếu has_role() không short-circuit,
    # dòng dưới sẽ raise lỗi từ google-cloud-bigquery, không phải return False êm.
    assert has_role("ngadt@hapas.vn", "admin")
    assert has_role("ngadt@hapas.vn", "embed")


def test_can_use_embeds_true_for_super_admin_without_bigquery():
    assert can_use_embeds("ngadt@hapas.vn")


if __name__ == "__main__":
    from _run import run_tests
    run_tests(globals())
