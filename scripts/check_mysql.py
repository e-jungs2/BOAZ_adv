from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from DATA_Analyst_Assistant_Agent import BackendAdapter


def main() -> int:
    adapter = BackendAdapter()
    datasource_id = adapter.get_default_datasource_id()

    print(f"project_root: {ROOT}")
    print(f"base_data_dir: {adapter.base_data_dir}")

    if not datasource_id:
        print("status: FAILED")
        print("reason: no default MySQL datasource was auto-registered")
        print("check: .env exists in the current working directory and includes MYSQL_HOST, MYSQL_DATABASE, MYSQL_USERNAME")
        return 1

    print(f"datasource_id: {datasource_id}")

    try:
        catalog = adapter.refresh_catalog(datasource_id)
        table_names = sorted(catalog.get("tables", {}).keys())
        print("catalog: OK")
        print(f"database: {catalog.get('database')}")
        print(f"table_count: {len(table_names)}")
        print(f"tables_preview: {table_names[:10]}")
    except Exception as exc:
        print("status: FAILED")
        print("stage: refresh_catalog")
        print(f"error: {type(exc).__name__}: {exc}")
        return 2

    try:
        run = adapter.create_run()
        result_ref = adapter.run_sql_preview(run.run_id, "SELECT 1 AS ok", datasource_id=datasource_id)
        print("query: OK")
        print(f"preview: {result_ref.preview}")
        print("status: SUCCESS")
        return 0
    except Exception as exc:
        print("status: FAILED")
        print("stage: run_sql_preview")
        print(f"error: {type(exc).__name__}: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
