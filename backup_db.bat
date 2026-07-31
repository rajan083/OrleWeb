@echo off
setlocal

set PGPASSWORD=root
set BACKUP_DIR=%~dp0backups

for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HH-mm"') do set TIMESTAMP=%%i

if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"

"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -U postgres -h localhost -d orle_dev -F c -f "%BACKUP_DIR%\orle_backup_%TIMESTAMP%.dump"

if errorlevel 1 (
    echo Backup FAILED - pg_dump returned an error.
    del "%BACKUP_DIR%\orle_backup_%TIMESTAMP%.dump" 2>nul
    exit /b 1
)

echo Backup complete: orle_backup_%TIMESTAMP%.dump

REM Keep only the last 14 backups
forfiles /p "%BACKUP_DIR%" /m orle_backup_*.dump /d -14 /c "cmd /c del @path" 2>nul

endlocal