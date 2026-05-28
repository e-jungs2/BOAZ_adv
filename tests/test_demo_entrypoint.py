from __future__ import annotations

from DATA_Analyst_Assistant_Agent.agents.sql import planner as planner_module
from DATA_Analyst_Assistant_Agent.backend_adapter import BackendAdapter
from DATA_Analyst_Assistant_Agent.demo import DemoScenario, main, resolve_scenarios, run_demo_scenarios


def _disable_default_datasource(monkeypatch) -> None:
    monkeypatch.setattr(BackendAdapter, "get_default_datasource_id", lambda self: None)


def test_full_demo_runs_comprehensive_and_mart_flows(tmp_path, monkeypatch) -> None:
    _disable_default_datasource(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(
        planner_module,
        "_call_llm_planner",
        lambda **kwargs: """
        {
          "selected_tables": ["orders"],
          "selected_columns": ["month", "revenue"],
          "generated_sql": "SELECT 1 AS month, 1 AS revenue",
          "reasoning": "llm planner demo",
          "confidence": 0.9
        }
        """,
    )
    results = run_demo_scenarios(
        [
            DemoScenario(
                "comprehensive",
                "프로파일과 분석 인사이트를 만들고 월별 매출 추이 차트까지 포함한 종합 분석 보고서를 만들어줘.",
            ),
            DemoScenario("mart", "반복 조회용 데이터마트 저장 후보를 만들어줘.", auto_approve=True),
        ],
        base_data_dir=tmp_path / ".demo_data",
        planner_mode="llm",
        require_llm_planner=True,
    )

    assert len(results) == 2

    comprehensive_result = results[0]
    assert comprehensive_result.initial_state.route_kind == "comprehensive"
    assert comprehensive_result.final_state.terminal_state.value == "completed"
    assert comprehensive_result.final_state.planner_mode == "llm"
    assert comprehensive_result.final_state.generated_sql == "SELECT 1 AS month, 1 AS revenue"
    assert comprehensive_result.final_state.completed_agents == [
        "sql_agent",
        "eda_agent",
        "analysis_agent",
        "visualization_agent",
        "report_agent",
    ]

    mart_result = results[1]
    assert mart_result.initial_state.terminal_state.value == "needs_user_approval"
    assert mart_result.auto_approved is True
    assert mart_result.final_state.mart_id is not None
    assert mart_result.final_state.terminal_state.value == "completed"
    assert "mart_metadata" in mart_result.final_state.artifact_ids


def test_demo_main_prints_summary(tmp_path, capsys, monkeypatch) -> None:
    _disable_default_datasource(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(
        planner_module,
        "_call_llm_planner",
        lambda **kwargs: """
        {
          "selected_tables": ["orders"],
          "selected_columns": ["month", "revenue"],
          "generated_sql": "SELECT 1 AS month, 1 AS revenue",
          "reasoning": "llm planner demo",
          "confidence": 0.9
        }
        """,
    )
    exit_code = main(
        [
            "--scenario",
            "trend",
            "--base-data-dir",
            str(tmp_path / ".demo_data"),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Route: trend" in captured.out
    assert "Planner: llm" in captured.out
    assert "SQL: SELECT 1 AS month, 1 AS revenue" in captured.out
    assert "Status: completed" in captured.out
    assert "Report:" in captured.out
    assert "llm.raw_response" not in captured.out


def test_demo_main_accepts_custom_query(tmp_path, capsys, monkeypatch) -> None:
    _disable_default_datasource(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(
        planner_module,
        "_call_llm_planner",
        lambda **kwargs: """
        {
          "query": "SELECT 1 AS answer"
        }
        """,
    )

    exit_code = main(
        [
            "--query",
            "간단한 요약을 보여줘",
            "--base-data-dir",
            str(tmp_path / ".demo_data"),
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Query: 간단한 요약을 보여줘" in captured.out
    assert "SQL: SELECT 1 AS answer" in captured.out


def test_resolve_scenarios_prompts_when_no_query_or_scenario(monkeypatch) -> None:
    from argparse import Namespace

    monkeypatch.setattr("builtins.input", lambda prompt: "월별 매출 추이를 보여줘")

    scenarios = resolve_scenarios(
        Namespace(
            query=None,
            scenario=None,
            pause_on_approval=False,
        )
    )

    assert len(scenarios) == 1
    assert scenarios[0].name == "custom"
    assert scenarios[0].query == "월별 매출 추이를 보여줘"


def test_demo_main_shows_raw_llm_only_when_requested(tmp_path, capsys, monkeypatch) -> None:
    _disable_default_datasource(monkeypatch)
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(
        planner_module,
        "_call_llm_planner",
        lambda **kwargs: """
        {
          "query": "SELECT 1 AS answer"
        }
        """,
    )

    main(
        [
            "--query",
            "간단한 요약을 보여줘",
            "--base-data-dir",
            str(tmp_path / ".demo_data"),
            "--show-llm-raw",
        ]
    )

    captured = capsys.readouterr()

    assert "llm.raw_response" in captured.out
