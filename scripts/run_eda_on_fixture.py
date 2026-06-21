"""EDA 다변수 차트 로직을 SQL/LLM 없이 fixture로 돌려보는 테스트 하네스 (모드 A: 코드, 토큰 0).

실행:
  PYTHONUTF8=1 .venv/Scripts/python.exe scripts/run_eda_on_fixture.py [fixture_name|all]

fixture(주문단위 등) + 입력계약을 읽어 차트 함수를 직접 호출하고, 차트마다
"그림 N장 / 조건 안 맞아 스킵"을 보고하고 발행되는 chart_requests를 출력한다.
Gemini/OpenRouter 호출 없음.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from DATA_Analyst_Assistant_Agent.agents.eda.fixtures import load_fixture
from DATA_Analyst_Assistant_Agent.agents.eda.tools import chart_requests as CR
from DATA_Analyst_Assistant_Agent.agents.eda.tools import visualize
from DATA_Analyst_Assistant_Agent.agents.eda.tools.reliability import assess_sample_reliability, detect_data_level

FIXTURES = ["f1_order_level", "f2_category_level", "f3_category_month"]


def _report(title: str, result: dict, requests: list) -> None:
    paths = result.get("chart_paths") or ([result["chart_path"]] if result.get("chart_path") else [])
    if not paths:
        print(f"  [{title}] SKIP — {result.get('skipped', '조건 미충족/데이터 없음')}")
        return
    print(f"  [{title}] 그림 {len(paths)}장: {[os.path.basename(p) for p in paths]}")
    for r in requests:
        print(f"      주문서> [{r['hint']}] {r['intent']}")


def run_one(name: str) -> None:
    df, c = load_fixture(name)
    out_dir = os.path.join(_REPO_ROOT, "daaa_outputs", "fixture_preview", name)
    visualize.set_output_dirs(out_dir)

    print(f"\n========== {name} ==========")
    print(f"rows={len(df)} | grain='{c.grain_hint}' level={c.level} | key={c.key_col} "
          f"numeric={c.numeric} datetime={c.datetime} target={c.target_candidates}")
    dl = detect_data_level(df, key_col=c.key_col, numeric_cols=c.numeric)
    rel = assess_sample_reliability(df, key_col=c.key_col, count_col=c.count, data_level=dl["level"])
    print(f"자가판정: level={dl['level']} ({dl['confidence']}) | {rel['note']}")

    target = c.target_candidates[0] if c.target_candidates else None
    cat2 = c.categorical[1] if len(c.categorical) > 1 else None

    # 1) 범주별 분포 (category x numeric)
    r = visualize.plot_grouped_box(df, key_col=c.key_col, measure_cols=c.numeric)
    _report("grouped_box (범주별 분포)", r, CR.from_grouped_box(r, c.key_col))

    # 2) target별 분포 (쿼리 정조준)
    r = visualize.plot_distribution_by_target(df, target_col=target, measure_cols=c.numeric)
    _report("dist_by_target (target별 분포)", r, CR.from_distribution_by_target(r))

    # 3) 시간 x 범주 (multiline)
    tcol = c.datetime[0] if c.datetime else None
    r = visualize.plot_multiline_timeseries(df, time_col=tcol, key_col=c.key_col, measure_cols=c.numeric)
    _report("multiline (시간x범주 추세)", r, CR.from_multiline(r))

    # 4) 범주 x 범주 (crosstab)
    r = visualize.plot_crosstab_heatmap(df, cat_a=c.key_col, cat_b=cat2)
    _report("crosstab (범주x범주)", r, CR.from_crosstab(r))

    print(f"output dir: {visualize.OUTPUT_DIR}")


def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = FIXTURES if arg == "all" else [arg]
    for n in names:
        run_one(n)
    print("\nDONE (LLM 호출 0)")


if __name__ == "__main__":
    main()
