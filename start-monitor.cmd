@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PYTHONPATH=%~dp0server"
where py >nul 2>&1
if not errorlevel 1 (
  set "PYTHON=py -3"
) else (
  set "PYTHON=python"
)

if not "%~1"=="" (
  set "FIRST_ARG=%~1"
  if "!FIRST_ARG:~0,1!"=="-" (
    %PYTHON% -m monitorctl_py desktop %*
  ) else (
    %PYTHON% -m monitorctl_py desktop --ssh "%~1"
  )
  goto :done
)

if exist "%~dp0monitor.config.json" (
  %PYTHON% -m monitorctl_py desktop --config "%~dp0monitor.config.json"
  goto :done
)

if defined TRAINING_MONITOR_SSH (
  %PYTHON% -m monitorctl_py desktop --ssh "%TRAINING_MONITOR_SSH%"
  goto :done
)

echo First run: enter the SSH alias or user@host of the training server.
echo For future launches, copy monitor.config.example.json to monitor.config.json.
set /p "TRAINING_MONITOR_SSH=SSH host: "
if not defined TRAINING_MONITOR_SSH (
  echo No SSH host was provided.
  goto :done
)
%PYTHON% -m monitorctl_py desktop --ssh "%TRAINING_MONITOR_SSH%"

:done
if errorlevel 1 pause
