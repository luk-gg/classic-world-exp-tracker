# Builds dist\MapleEXPTracker.exe (needs: pip install -r requirements.txt -r requirements-dev.txt)
# (PyInstaller logs to stderr, so errors are judged by its exit code, not by PowerShell's error stream.)
Set-Location $PSScriptRoot
python -m PyInstaller --noconfirm --clean exp_tracker.spec
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed ($LASTEXITCODE)"; exit $LASTEXITCODE }
$exe = Get-Item "dist\MapleEXPTracker.exe"
"Built $($exe.FullName)  ({0:N1} MB)" -f ($exe.Length / 1MB)
