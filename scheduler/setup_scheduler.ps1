# =============================================================================
#  NDC Pipeline - Task Scheduler Setup
#  Run this ONCE on any machine to register the 4 daily scheduled tasks.
#
#  HOW TO RUN (on the client machine):
#  ─────────────────────────────────────────────────────────────────────────────
#  1. Open PowerShell or CMD  (no Administrator needed)
#  2. cd into the project folder, e.g.:
#       cd "C:\Projects\NDC-Tracking-Automation"
#  3. Run:
#       powershell -ExecutionPolicy Bypass -File scheduler\setup_scheduler.ps1
#  ─────────────────────────────────────────────────────────────────────────────
#  After running, tasks fire silently at: 10AM | 1PM | 4PM | 7PM every day.
#  If the PC was OFF/asleep at trigger time, task runs automatically on next boot.
# =============================================================================


# ── Resolve paths (auto-detects project root from this script's location) ─────
$ROOT     = Split-Path -Parent $PSScriptRoot        # scheduler/ → project root
$PYTHONW  = Join-Path $ROOT ".venv\Scripts\pythonw.exe"
$SCRIPT   = Join-Path $ROOT "scheduler\run_pipeline.py"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  NDC Pipeline - Task Scheduler Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Project root : $ROOT"
Write-Host "  Python       : $PYTHONW"
Write-Host "  Pipeline     : $SCRIPT"
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Check virtual environment exists ─────────────────────────────────────────
if (-not (Test-Path $PYTHONW)) {
    Write-Host "[ERROR] pythonw.exe not found: $PYTHONW" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Set up the virtual environment first:" -ForegroundColor Yellow
    Write-Host "    cd `"$ROOT`""
    Write-Host "    python -m venv .venv"
    Write-Host "    .venv\Scripts\pip install -e ."
    Write-Host ""
    exit 1
}

# ── Task configuration ────────────────────────────────────────────────────────
$action = New-ScheduledTaskAction `
    -Execute   $PYTHONW `
    -Argument  "`"$SCRIPT`"" `
    -WorkingDirectory $ROOT

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances        IgnoreNew `
    -ExecutionTimeLimit       (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$tasks = @(
    @{ Name = "NDC_Pipeline_1000"; Time = "10:00" },
    @{ Name = "NDC_Pipeline_1300"; Time = "13:00" },
    @{ Name = "NDC_Pipeline_1600"; Time = "16:00" },
    @{ Name = "NDC_Pipeline_1900"; Time = "19:00" }
)

# ── Register tasks ────────────────────────────────────────────────────────────
$failed = 0
foreach ($t in $tasks) {
    try {
        $trigger = New-ScheduledTaskTrigger -Daily -At $t.Time
        Register-ScheduledTask `
            -TaskName $t.Name `
            -Action   $action `
            -Trigger  $trigger `
            -Settings $settings `
            -RunLevel   Limited `
            -Force | Out-Null
        Write-Host "  [OK] $($t.Name)  ->  $($t.Time) daily" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] $($t.Name): $_" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""

if ($failed -eq 0) {
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "  SUCCESS! All tasks registered." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Runs silently at: 10AM | 1PM | 4PM | 7PM" -ForegroundColor Green
    Write-Host "  Missed triggers fire automatically on next boot/wake." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Logs: $ROOT\logs\pipeline.log" -ForegroundColor Gray
    Write-Host "============================================================" -ForegroundColor Green
} else {
    Write-Host "[WARNING] $failed task(s) failed to register." -ForegroundColor Yellow
    Write-Host "          Make sure you ran this as Administrator." -ForegroundColor Yellow
}

Write-Host ""
