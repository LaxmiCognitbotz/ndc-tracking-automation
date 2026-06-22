"""
NDC Pipeline Orchestrator
--------------------------
Runs the full pipeline in sequence:
  1. scripts/download_ndc_report.py  — downloads the Excel report from Oracle Fusion
  2. scripts/upload_to_sharepoint.py — uploads the latest file in NDC_Reports/ to SharePoint

This script lives in the  scheduler/  folder.
It is called automatically by Windows Task Scheduler via setup_scheduler.bat.
All output is appended to logs/pipeline.log (in the project root).
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
# This file is at:  <project_root>/scheduler/run_pipeline.py
# So ROOT_DIR goes  one level up  →  <project_root>/
ROOT_DIR = Path(__file__).parent.parent

LOG_DIR  = ROOT_DIR / "logs"
LOG_FILE = LOG_DIR  / "pipeline.log"
SCRIPTS  = ROOT_DIR / "scripts"
PYTHON   = ROOT_DIR / ".venv" / "Scripts" / "python.exe"

LOG_DIR.mkdir(parents=True, exist_ok=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str):
    line = f"[{ts()}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_script(script_path: Path, args: list = None) -> int:
    """Run a Python script as a subprocess and stream its output to the log."""
    log(f">>> Starting : {script_path.name}")
    log(f"    Full path: {script_path}")

    cmd = [str(PYTHON), str(script_path)]
    if args:
        cmd.extend(args)

    # Windows-specific flag to hide console window
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

        if result.stdout.strip():
            for line in result.stdout.splitlines():
                log(f"  [OUT] {line}")

        if result.stderr.strip():
            for line in result.stderr.splitlines():
                log(f"  [ERR] {line}")

        log(f"<<< Finished : {script_path.name}  |  exit code: {result.returncode}")
        return result.returncode

    except FileNotFoundError:
        log(f"[FATAL] Python interpreter not found at: {PYTHON}")
        log("        Fix: python -m venv .venv  →  .venv\\Scripts\\pip install -e .")
        return -1
    except Exception as e:
        log(f"[FATAL] Unexpected error running {script_path.name}: {e}")
        return -1


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log("=" * 70)
    log("NDC PIPELINE STARTED")
    log(f"Project root : {ROOT_DIR}")
    log("=" * 70)

    if not PYTHON.exists():
        log(f"[FATAL] Virtual-env Python not found: {PYTHON}")
        log("        Run:  python -m venv .venv  then  .venv\\Scripts\\pip install -e .")
        sys.exit(1)

    # ── Step 1: Download report from Oracle Fusion ────────────────────────────
    exit_dl = run_script(SCRIPTS / "download_ndc_report.py")

    if exit_dl != 0:
        log(f"[WARNING] Download exited with code {exit_dl}.")
        log("          Upload will still attempt in case a previous report exists.")

    # ── Step 2: Upload latest report to SharePoint ────────────────────────────
    # Limit scheduler run to only upload NDC reports, avoiding F&F files
    exit_ul = run_script(SCRIPTS / "upload_to_sharepoint.py", ["--type", "ndc"])

    if exit_ul != 0:
        log(f"[ERROR] Upload failed with exit code {exit_ul}.")

    # ── Summary ───────────────────────────────────────────────────────────────
    status_dl = "OK" if exit_dl == 0 else f"FAILED({exit_dl})"
    status_ul = "OK" if exit_ul == 0 else f"FAILED({exit_ul})"
    log("=" * 70)
    log(f"PIPELINE COMPLETE  |  Download: {status_dl}  |  Upload: {status_ul}")
    log("=" * 70)

    sys.exit(exit_dl if exit_dl != 0 else exit_ul)


if __name__ == "__main__":
    main()
