# ===========================================================================
# LEO PRODUCTS — run the production server on a Windows PC (Waitress).
#
# Before the first run:
#   * install Python 3.12 and create .venv (DEVELOPMENT_GUIDE §2)
#   * .\.venv\Scripts\pip install -r requirements-production.txt
#   * create .env from deploy\env.production.example and fill it in
#     (single shop PC: ALLOWED_HOSTS=127.0.0.1,localhost and LOCAL_HTTP_ONLY=True)
#
# Run from PowerShell (in the project folder):
#   powershell -ExecutionPolicy Bypass -File deploy\windows\start-server.ps1
# Stop with Ctrl+C. To start automatically at sign-in, see DEVELOPMENT_GUIDE ("Going live").
# ===========================================================================
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")

$env:DJANGO_SETTINGS_MODULE = "config.settings.production"
$python = ".\.venv\Scripts\python.exe"

& $python manage.py check --deploy --fail-level ERROR
& $python manage.py migrate --noinput
& $python manage.py collectstatic --noinput

$listen = if ($env:LEO_LISTEN) { $env:LEO_LISTEN } else { "127.0.0.1:8000" }
Write-Host "LEO PRODUCTS is running at http://$listen/  (Ctrl+C to stop)"
& ".\.venv\Scripts\waitress-serve.exe" --listen=$listen --threads=8 config.wsgi:application
