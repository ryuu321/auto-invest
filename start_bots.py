"""全ボット起動スクリプト — python start_bots.py"""
import sys, os, subprocess
from pathlib import Path

os.chdir(Path(__file__).parent)
os.environ["PYTHONIOENCODING"] = "utf-8"

BASE = Path(__file__).parent
BOTS = [
    ("短期", BASE / "short"  / "main.py"),
    ("中期", BASE / "medium" / "main.py"),
    ("長期", BASE / "long"   / "main.py"),
]

print("[AI Holdings] 投資ボット全モード起動")
print("  短期: 1時間ごと（BTC テクニカル）")
print("  中期: 24時間ごと（クロス戦略）")
print("  長期: 7日ごと（ファンダメンタルズ）\n")

processes = []
for name, path in BOTS:
    if not path.exists():
        print(f"[!] {name}: {path} が見つかりません")
        continue
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    p = subprocess.Popen([sys.executable, "-u", str(path)], env=env)
    processes.append((name, p))
    print(f"[OK] {name}ボット起動 (PID={p.pid})")

print("\n全ボット起動完了。Ctrl+C で停止。\n")

try:
    for name, p in processes:
        p.wait()
except KeyboardInterrupt:
    print("\n[STOP] 全ボット停止中...")
    for name, p in processes:
        p.terminate()
        print(f"  {name}: 停止")
