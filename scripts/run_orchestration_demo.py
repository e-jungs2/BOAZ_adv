from __future__ import annotations

import argparse
import json
from pathlib import Path

from DATA_Analyst_Assistant_Agent import BackendAdapter, SQLAgentSupervisor


def _artifact_preview(adapter: BackendAdapter, artifact_id: str) -> dict:
    artifact = adapter.get_artifact(artifact_id)
    return {
        "artifact_id": artifact.artifact_id,
        "type": str(artifact.type),
        "filename": artifact.filename,
        "metadata": artifact.metadata,
        "preview": artifact.preview,
        "local_path": str(artifact.local_path) if artifact.local_path else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DATA_Analyst_Assistant_Agent orchestration demo.")
    parser.add_argument("query", help="User question to run through the orchestration graph.")
    parser.add_argument("--thread-id", default="demo-thread", help="Optional thread id for the backend run.")
    parser.add_argument("--datasource-id", default=None, help="Optional backend datasource id.")
    args = parser.parse_args()

    adapter = BackendAdapter()
    supervisor = SQLAgentSupervisor(adapter)
    state = supervisor.run(args.query, thread_id=args.thread_id, datasource_id=args.datasource_id)

    print("\n=== Orchestration Result ===")
    print(f"terminal_state: {state.terminal_state}")
    print(f"route_kind:      {state.route_kind}")
    print(f"current_step:    {state.current_step}")
    print(f"completed:       {state.completed_agents}")
    print(f"generated_sql:   {state.generated_sql or '(none)'}")

    if state.error_state:
        print("\n=== Error State ===")
        print(json.dumps(state.error_state, ensure_ascii=False, indent=2, default=str))

    print("\n=== Artifacts ===")
    for agent_name, artifact_ids in state.artifact_ids.items():
        print(f"\n[{agent_name}]")
        for artifact_id in artifact_ids:
            print(json.dumps(_artifact_preview(adapter, artifact_id), ensure_ascii=False, indent=2, default=str))

    print("\n=== Data Dir ===")
    print(Path(adapter.base_data_dir).resolve())


if __name__ == "__main__":
    main()
