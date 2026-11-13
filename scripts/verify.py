"""本地一键验收（会覆盖 results/ 对应实验数据文件）。"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = [
    ('unit_tests', [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v']),
    ('benchmarks', [sys.executable, 'scripts/benchmark.py']),
    ('stress', [sys.executable, 'scripts/stress.py']),
    ('production_benchmark', [sys.executable, 'scripts/production_benchmark.py']),
    ('server_smoke', [sys.executable, 'scripts/smoke_server.py']),
    ('compile', [sys.executable, '-m', 'compileall', '-q', 'simlife', 'tests', 'scripts']),
]

def main():
    results = {}
    for key, command in STEPS:
        process = subprocess.run(command, cwd=ROOT, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 timeout=180, check=False)
        results[key] = {'exit_code': process.returncode, 'command': ' '.join(command),
                        'tail': '\n'.join(process.stdout.splitlines()[-8:])}
        print(f'{key}: {"PASS" if process.returncode == 0 else "FAIL"}')
        if process.returncode != 0:
            print(results[key]['tail'])
            break
    results['all_passed'] = all(x['exit_code'] == 0 for key, x in results.items()
                                 if isinstance(x, dict) and 'exit_code' in x)
    path = ROOT / 'results' / 'verification.json'
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    print('verification report:', path.relative_to(ROOT))
    if not results['all_passed'] or len(results) != len(STEPS) + 1:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
