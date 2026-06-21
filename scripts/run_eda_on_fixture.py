"""EDA 차트 로직을 SQL/LLM 없이 fixture로 돌려보는 테스트 하네스 (모드 A: 코드, 토큰 0).

실행:
  PYTHONUTF8=1 .venv/Scripts/python.exe scripts/run_eda_on_fixture.py [fixture_name]

fixture(주문단위 등) + 입력계약을 읽어 차트 함수를 직접 호출하고, 발행되는
chart_requests(주문서)와 생성된 PNG 경로를 출력한다. Gemini/OpenRouter 호출 없음.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from DATA_Analyst_Assistant_Agent.agents.eda.fixtures import load_fixture
from DATA_Analyst_Assistant_Agent.agents.eda.tools import visualize
from DATA_Analyst_Assistant_Agent.agents.eda.tools.chart_requests import from_grouped_box
from DATA_Analyst_Assistant_Agent.agents.eda.tools.reliability import (
    assess_sample_reliability, build_cautions, detect_data_level,
)


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "f1_order_level"
    df, c = load_fixture(name)

    # 미리보기 출력 폴더(추적 안 함: daaa_outputs/)
    out_dir = os.path.join(_REPO_ROOT, "daaa_outputs", "fixture_preview", name)
    visualize.set_output_dirs(out_dir)

    print(f"[{name}] rows={len(df)} | grain='{c.grain_hint}' level={c.level}")
    print(f"  key_col={c.key_col} numeric={c.numeric} count={c.count} target={c.target_candidates}")

    # grain 자가판정 (계약과 일치하는지)
    dl = detect_data_level(df, key_col=c.key_col, numeric_cols=c.numeric)
    rel = assess_sample_reliability(df, key_col=c.key_col, count_col=c.count, data_level=dl["level"])
    print(f"  detected level={dl['level']} ({dl['confidence']}) | {rel['note']}")

    # 다변수 차트: 그룹별 분포 비교
    res = visualize.plot_grouped_box(df, key_col=c.key_col, measure_cols=c.numeric)
    if res.get("skipped"):
        print(f"  grouped_box SKIP: {res['skipped']}")
    else:
        print(f"  grouped_box charts: {[os.path.basename(p) for p in res.get('chart_paths', [])]}")
        for r in from_grouped_box(res, c.key_col):
            print(f"    주문서> [{r['hint']}] {r['intent']}")
            note = (r.get('stats') or {}).get('note')
            if note:
                print(f"            stats.note: {note}")

    print(f"  output dir: {visualize.OUTPUT_DIR}")
    print("DONE (LLM 호출 0)")


if __name__ == "__main__":
    main()
