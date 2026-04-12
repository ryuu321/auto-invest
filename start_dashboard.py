"""ダッシュボード起動スクリプト — python start_dashboard.py"""
import sys, os, subprocess, webbrowser, time, threading
from pathlib import Path

os.chdir(Path(__file__).parent)
os.environ["PYTHONIOENCODING"] = "utf-8"

# GitHub Actions の最新データを取得
print("[SYNC] GitHubから最新データを取得中...")
try:
    result = subprocess.run(
        ["git", "pull", "--rebase"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        print(f"[SYNC] {result.stdout.strip() or '最新状態です'}")
    else:
        print(f"[SYNC] スキップ（オフラインまたはエラー）: {result.stderr.strip()[:80]}")
except Exception as e:
    print(f"[SYNC] スキップ: {e}")

sys.path.insert(0, str(Path(__file__).parent / "dashboard"))

def open_browser():
    time.sleep(2)
    webbrowser.open("http://localhost:5000")

threading.Thread(target=open_browser, daemon=True).start()

print("[AI Holdings] ダッシュボード起動: http://localhost:5000")
print("終了: Ctrl+C\n")

import dashboard.app as app_module
app_module.app.run(host="0.0.0.0", port=5000, debug=False)
