"""Sinh fixture cho app/web/preview.html: chạy lại ĐÚNG sql_per_kpi của 1 build có
thật trên BigQuery (qua bq CLI) rồi ghép thành y hệt response GET /api/dashboard/{id}."""
import json, subprocess, sys, datetime

PROJECT = "surya-495408"

def bq_json(sql, params=None):
    cmd = ["bq", "query", "--project_id=" + PROJECT, "--format=json", "--use_legacy_sql=false", "--quiet", "--max_rows=100000"]
    for p in (params or []):
        cmd.append("--parameter=" + p)
    cmd.append(sql)
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("bq failed:\n" + out.stderr)
    return json.loads(out.stdout or "[]")

def make(dashboard_id, start, end, outfile):
    bp = bq_json(f"""SELECT TO_JSON_STRING(spec) AS spec FROM
      `{PROJECT}.12_data_agent_log.raw_dashboard_builder_v_current_blueprints`
      WHERE dashboard_id = '{dashboard_id}'""")
    if not bp:
        sys.exit(f"Không có blueprint nào cho dashboard_id '{dashboard_id}'.")
    blueprint = json.loads(bp[0]["spec"])

    bd = bq_json(f"""SELECT TO_JSON_STRING(sql_per_kpi) AS q FROM
      `{PROJECT}.12_data_agent_log.raw_dashboard_builder_builds`
      WHERE dashboard_id = '{dashboard_id}' AND status = 'active'
      ORDER BY created_at DESC LIMIT 1""")
    if not bd:
        sys.exit(f"Dashboard '{dashboard_id}' chưa có build nào status='active' — "
                 "không lấy được SQL để sinh fixture.")
    sql_per_kpi = json.loads(bd[0]["q"])

    results = []
    for q in sql_per_kpi:
        rows = bq_json(q["sql"], [f"start_date:DATE:{start}", f"end_date:DATE:{end}"])
        # bq CLI trả mọi giá trị dạng string — ép số về number đúng như google-cloud-bigquery
        for r in rows:
            for k, v in list(r.items()):
                if k in (q["y_field"],) and v is not None:
                    r[k] = float(v) if "." in str(v) else int(v)
        results.append({
            "kpi_name": q["kpi_name"], "x_field": q["x_field"], "y_field": q["y_field"],
            "series_field": q.get("series_field") or "", "rows": rows,
        })
        print(f"  {q['kpi_name']}: {len(rows)} rows", file=sys.stderr)

    fixture = {"blueprint": blueprint, "results": results,
               "default_start_date": start, "default_end_date": end}
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False, indent=1)
    print(f"-> {outfile}", file=sys.stderr)

if __name__ == "__main__":
    make(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
