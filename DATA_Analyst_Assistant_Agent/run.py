from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from DATA_Analyst_Assistant_Agent import BackendAdapter, SQLAgentSupervisor
from DATA_Analyst_Assistant_Agent.models import OrchestrationState


ROOT_DIR = Path(__file__).resolve().parents[1]


def _normalize_env_aliases() -> None:
    aliases = {
        "DB_HOST": "MYSQL_HOST",
        "DB_USER": "MYSQL_USERNAME",
        "DB_NAME": "MYSQL_DATABASE",
        "DB_PORT": "MYSQL_PORT",
        "DB_PASSWORD": "MYSQL_PASSWORD",
        "GOOGLE_API_KEY": "GEMINI_API_KEY",
    }
    for target, source in aliases.items():
        if not os.getenv(target) and os.getenv(source):
            os.environ[target] = os.getenv(source, "")
    os.environ.setdefault("DB_PASSWORD", "")


def _state_summary(state: OrchestrationState) -> dict[str, Any]:
    return {
        "run_id": state.run_id,
        "thread_id": state.thread_id,
        "datasource_id": state.datasource_id,
        "terminal_state": state.terminal_state.value if state.terminal_state else None,
        "route_kind": state.route_kind,
        "planner_mode": state.planner_mode,
        "current_step": state.current_step,
        "completed_agents": state.completed_agents,
        "remaining_agents": state.remaining_agents,
        "generated_sql": state.generated_sql,
        "artifact_ids": state.artifact_ids,
        "approval_ids": state.approval_ids,
        "mart_id": state.mart_id,
        "error_state": state.error_state,
    }


def _artifact_preview(adapter: BackendAdapter, artifact_id: str) -> dict[str, Any]:
    artifact = adapter.get_artifact(artifact_id)
    return {
        "artifact_id": artifact.artifact_id,
        "type": str(artifact.type),
        "uri": artifact.uri,
        "metadata": artifact.metadata,
        "preview": artifact.preview,
        "local_path": str(artifact.local_path) if artifact.local_path else None,
    }


def _copy_artifacts(output_dir: Path, artifacts: dict[str, list[dict[str, Any]]]) -> None:
    artifact_root = output_dir / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    for agent_name, items in artifacts.items():
        agent_dir = artifact_root / agent_name
        agent_dir.mkdir(parents=True, exist_ok=True)
        for item in items:
            local_path = item.get("local_path")
            if not local_path:
                continue
            source = Path(local_path)
            if source.exists() and source.is_file():
                destination = agent_dir / f"{item['artifact_id']}_{source.name}"
                shutil.copy2(source, destination)


def _write_outputs(adapter: BackendAdapter, state: OrchestrationState, query: str, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        agent_name: [_artifact_preview(adapter, artifact_id) for artifact_id in artifact_ids]
        for agent_name, artifact_ids in state.artifact_ids.items()
    }
    summary = {
        "query": query,
        **_state_summary(state),
        "artifacts": artifacts,
    }

    summary_path = output_dir / "run_summary.json"
    sql_path = output_dir / "generated_sql.sql"
    artifact_manifest_path = output_dir / "artifact_manifest.json"

    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    sql_path.write_text(state.generated_sql or "", encoding="utf-8")
    artifact_manifest_path.write_text(json.dumps(artifacts, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _copy_artifacts(output_dir, artifacts)

    return {
        "output_dir": output_dir,
        "summary": summary_path,
        "generated_sql": sql_path,
        "artifact_manifest": artifact_manifest_path,
    }


def _print_text_summary(
    state: OrchestrationState,
    adapter: BackendAdapter,
    *,
    outputs: dict[str, Path] | None,
    show_sql: bool,
) -> None:
    print("\n=== Orchestration Result ===")
    print(f"terminal_state: {state.terminal_state}")
    print(f"route_kind:      {state.route_kind}")
    print(f"planner_mode:    {state.planner_mode}")
    print(f"current_step:    {state.current_step}")
    print(f"completed:       {state.completed_agents}")

    if outputs:
        print(f"generated_sql:   {outputs['generated_sql']}")
        print(f"result_folder:   {outputs['output_dir']}")
        print(f"run_summary:     {outputs['summary']}")
    else:
        print("generated_sql:   (output disabled)")

    if state.approval_ids:
        print(f"approval_ids:   {state.approval_ids}")

    if state.artifact_ids:
        print("\n=== Artifacts ===")
        for agent_name, artifact_ids in state.artifact_ids.items():
            print(f"{agent_name}: {artifact_ids}")

    if show_sql:
        print("\n=== Generated SQL ===")
        print(state.generated_sql or "(empty)")

    if state.error_state:
        print("\n=== Error State ===")
        print(json.dumps(state.error_state, ensure_ascii=False, indent=2, default=str))

    print("\n=== Data Dir ===")
    print(Path(adapter.base_data_dir).resolve())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run DATA_Analyst_Assistant_Agent directly through SQLAgentSupervisor.",
    )
    parser.add_argument("query", nargs="?", help="User analysis question. If omitted, stdin prompt is used.")
    parser.add_argument("--thread-id", default="daaa-manual-run", help="Thread id for the backend run.")
    parser.add_argument("--datasource-id", default=None, help="Optional backend datasource id.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON summary.")
    parser.add_argument("--show-sql", action="store_true", help="Print generated SQL in text output.")
    parser.add_argument("--dotenv", default=".env", help="Path to dotenv file. Defaults to .env.")
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "daaa_outputs" / "latest"),
        help="Directory for run_summary.json, generated_sql.sql, and copied artifacts.",
    )
    parser.add_argument("--no-output", action="store_true", help="Do not write output files.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    load_dotenv(args.dotenv)
    _normalize_env_aliases()

    query = args.query or input("Query: ").strip()
    if not query:
        raise SystemExit("Query is empty.")

    adapter = BackendAdapter()
    supervisor = SQLAgentSupervisor(adapter)
    state = supervisor.run(query, thread_id=args.thread_id, datasource_id=args.datasource_id)
    outputs = None
    if not args.no_output:
        outputs = _write_outputs(adapter, state, query, Path(args.output_dir))

    if args.json:
        payload = _state_summary(state)
        if outputs:
            payload["outputs"] = {key: str(value) for key, value in outputs.items()}
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        _print_text_summary(state, adapter, outputs=outputs, show_sql=args.show_sql)


if __name__ == "__main__":
    main()
