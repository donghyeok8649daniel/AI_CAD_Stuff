"""Start/reuse the local CAD server and open its UI. No keys in URLs or files."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
PORT = int(os.getenv("CADSTUDIO_PORT", "18760"))
URL = f"http://127.0.0.1:{PORT}"


def refresh_user_environment():
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                for name in ("OPENAI_API_KEY", "OPENAI_MODEL"):
                    try:
                        value, _ = winreg.QueryValueEx(key, name)
                        if value:
                            os.environ[name] = value
                    except FileNotFoundError:
                        pass
        except OSError:
            pass


def server_status():
    try:
        with urllib.request.urlopen(URL+"/api/status", timeout=2) as response:
            return json.load(response)
    except (OSError, ValueError, urllib.error.URLError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--foreground", action="store_true")
    args = parser.parse_args()
    refresh_user_environment()
    os.chdir(ROOT)
    if args.foreground:
        import uvicorn
        from cadstudio import server as application
        running = uvicorn.Server(uvicorn.Config(application.app, host="127.0.0.1", port=PORT, log_level="warning"))
        application.shutdown_callback = lambda: setattr(running, "should_exit", True)
        running.run()
        return
    status = server_status()
    if status and status.get("app") != "prompt-cad-studio":
        raise RuntimeError(f"Port {PORT} is already in use. Set CADSTUDIO_PORT to another local port.")
    if not status:
        data = ROOT / "data"
        data.mkdir(exist_ok=True)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        with (data / "server.log").open("a", encoding="utf-8") as log:
            child = subprocess.Popen([sys.executable, str(ROOT / "launch.py"), "--foreground"], cwd=ROOT, stdout=log, stderr=log, creationflags=flags)
        (data / "server.pid").write_text(str(child.pid), encoding="ascii")
        for _ in range(60):
            if child.poll() is not None:
                raise RuntimeError("CAD server stopped. Check data/server.log and run setup.ps1.")
            status = server_status()
            if status and status.get("app") == "prompt-cad-studio":
                break
            time.sleep(.5)
        else:
            raise RuntimeError("CAD server did not become ready. Check data/server.log.")
    if not args.no_browser:
        webbrowser.open(URL)
    print(URL)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if sys.platform == "win32" and sys.executable.lower().endswith("pythonw.exe"):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(error), "Prompt CAD Studio", 0x10)
        else:
            raise
