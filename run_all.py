"""
3モード一括起動スクリプト
短期・中期・長期を並列で動かす
"""

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent

BOTS = [
    ("短期", BASE / "short"  / "main.py"),
    ("中期", BASE / "medium" / "main.py"),
    ("長期", BASE / "long"   / "main.py"),
]


def main():
    print("[AI Holdings] 投資ボット全モード起動")
    print("  短期: 1時間ごと（BTC テクニカル）")
    print("  中期: 24時間ごと（BTC+株 ゴールデンクロス）")
    print("  長期: 7日ごと（株 ファンダメンタルズ）")
    print()

    processes = []
    for name, path in BOTS:
        if not path.exists():
            print(f"[!] {name}: {path} が見つかりません")
            continue
        p = subprocess.Popen(
            [sys.executable, "-u", str(path)],
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )
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


if __name__ == "__main__":
    main()
