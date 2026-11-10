@echo off
setlocal EnableDelayedExpansion
rem ============================================================
rem  Fire Board Estimator - database backup
rem
rem  - Dumps the whole PostgreSQL database (materials, prices,
rem    systems, users, calculation history, quotations)
rem  - Daily backups are kept for DAILY_KEEP days; the backup made
rem    on the 1st of each month is also copied to "monthly" and kept
rem    for MONTHLY_KEEP days
rem  - Results are written to backup.log; exit code 1 on failure
rem    (Task Scheduler shows 0x1)
rem  - Put this file in the fireboard folder (next to docker-compose.yml)
rem  - This file is plain ASCII on purpose: Chinese text in .bat files
rem    can be mis-read by cmd.exe
rem ============================================================

rem ---------- Settings ----------
set "BACKUP_DIR=C:\fireboard_backup"
set "DAILY_KEEP=14"
set "MONTHLY_KEEP=400"
rem Optional second copy, e.g. \\NAS\backup\fireboard  (leave empty to skip)
set "COPY_TO="

rem ---------- Prepare ----------
cd /d "%~dp0"
set "DAILY=%BACKUP_DIR%\daily"
set "MONTHLY=%BACKUP_DIR%\monthly"
set "LOG=%BACKUP_DIR%\backup.log"
if not exist "%DAILY%" mkdir "%DAILY%"
if not exist "%MONTHLY%" mkdir "%MONTHLY%"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do set "STAMP=%%i"
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format dd"') do set "DAY=%%i"
set "FILE=%DAILY%\fireboard-%STAMP%.dump"
set "TMP_IN_DB=/tmp/fb_backup.dump"

call :log "---------- Backup started %STAMP% ----------"

rem ---------- 1. Docker and database must be running ----------
docker info >nul 2>&1
if errorlevel 1 (
    call :log "[FAILED] Docker is not running. Open Docker Desktop - the PC must be logged in."
    goto fail
)
docker compose exec -T db pg_isready >nul 2>&1
if errorlevel 1 (
    call :log "[FAILED] Database container is not running. Run: docker compose up -d"
    goto fail
)

rem ---------- 2. Dump inside the db container ----------
rem User and database names come from the container settings - no password here.
docker compose exec -T db sh -c "pg_dump -U $POSTGRES_USER -Fc -f %TMP_IN_DB% $POSTGRES_DB"
if errorlevel 1 (
    call :log "[FAILED] pg_dump failed."
    goto fail
)

rem ---------- 3. Check the dump can be read ----------
docker compose exec -T db pg_restore --list %TMP_IN_DB% >nul 2>&1
if errorlevel 1 (
    call :log "[FAILED] Backup file is damaged - pg_restore cannot read it."
    goto fail
)

rem ---------- 4. Copy to Windows, remove the temp file in the container ----------
docker compose cp db:%TMP_IN_DB% "%FILE%" >nul 2>&1
if errorlevel 1 (
    call :log "[FAILED] Could not copy the backup to %DAILY%"
    goto fail
)
docker compose exec -T db rm -f %TMP_IN_DB% >nul 2>&1

set "SIZE=0"
for %%A in ("%FILE%") do set "SIZE=%%~zA"
if !SIZE! LSS 1024 (
    call :log "[FAILED] Backup file too small - !SIZE! bytes: %FILE%"
    goto fail
)
call :log "[OK] %FILE% - !SIZE! bytes"

rem ---------- 5. Monthly copy on the 1st ----------
if "%DAY%"=="01" (
    copy /y "%FILE%" "%MONTHLY%\" >nul
    if errorlevel 1 (call :log "[WARNING] Could not save the monthly copy") else (call :log "Monthly copy saved")
)

rem ---------- 6. Optional copy to NAS ----------
if defined COPY_TO (
    if not exist "%COPY_TO%" mkdir "%COPY_TO%" >nul 2>&1
    copy /y "%FILE%" "%COPY_TO%\" >nul 2>&1
    if errorlevel 1 (call :log "[WARNING] Could not copy to %COPY_TO% - the backup itself is OK") else (call :log "Copied to %COPY_TO%")
)

rem ---------- 7. Delete old backups ----------
forfiles /p "%DAILY%" /m *.dump /d -%DAILY_KEEP% /c "cmd /c del @path" >nul 2>&1
forfiles /p "%MONTHLY%" /m *.dump /d -%MONTHLY_KEEP% /c "cmd /c del @path" >nul 2>&1
call :log "Done."
exit /b 0

:fail
docker compose exec -T db rm -f %TMP_IN_DB% >nul 2>&1
call :log "Backup FAILED - see the messages above."
exit /b 1

:log
echo %~1
>>"%LOG%" echo [%date% %time:~0,8%] %~1
exit /b 0
