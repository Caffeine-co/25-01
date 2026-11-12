"""演示：模拟 LLM 的提议仍须受 World 裁决。无需网络或 API Key。"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simlife.config import load_scenario
from simlife.engine import WorldRuntime
from simlife.cognition import CognitionService, ScriptedBackend

ROOT = Path(__file__).resolve().parents[1]


def main():
    world = WorldRuntime(load_scenario(ROOT / 'examples/scenarios/apartment_sustainable.json'))
    world.run_until(0)

    # 1. 世界不允许从卧室跳去画室，模型这条提议只能被拒绝。
    model = ScriptedBackend('{"reply":"我现在去画室。", '
                            '"action":{"kind":"move","target":"studio"}}')
    result = CognitionService(model).interact(world, 'resident_01', 'user', '去画室')
    print('不可执行的建议：', result.reason, 'accepted =', result.action_accepted)
    print('真实位置：', world.lives['resident_01'].location)

    # 2. 移动到相邻走廊是合法的，但需要两分钟时间完成。
    model = ScriptedBackend('{"reply":"我先去走廊。", '
                            '"action":{"kind":"move","target":"hall"}}')
    result = CognitionService(model).interact(world, 'resident_01', 'user', '先去走廊')
    print('合法建议：', result.reason, 'accepted =', result.action_accepted)
    print('行动刚开始的位置：', world.lives['resident_01'].location)
    world.run_until(2)
    print('完成后的位置：', world.lives['resident_01'].location)
    print('审计事件数：', len(world.pending_log))

if __name__ == '__main__':
    main()
