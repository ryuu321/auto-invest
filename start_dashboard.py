"""ダッシュボード起動スクリプト — python start_dashboard.py"""
import sys, os, webbrowser, time, threading
from pathlib import Path

os.chdir(Path(__file__).parent)
os.environ["PYTHONIOENCODING"] = "utf-8"

sys.path.insert(0, str(Path(__file__).parent / "dashboard"))

def open_browser():
    time.sleep(2)
    webbrowser.open("http://localhost:5000")

threading.Thread(target=open_browser, daemon=True).start()

print("[AI Holdings] ダッシュボード起動: http://localhost:5000")
print("終了: Ctrl+C\n")

import dashboard.app as app_module
app_module.app.run(host="0.0.0.0", port=5000, debug=False)
