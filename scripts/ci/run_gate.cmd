@echo off
where py >nul 2>nul
if not errorlevel 1 goto use_py
where python >nul 2>nul
if not errorlevel 1 goto use_python
echo agentic gate: Python 3.9+ was not found 1>&2
exit /b 2

:use_py
py -3 "%~dp0check_all.py" %*
exit /b %errorlevel%

:use_python
python "%~dp0check_all.py" %*
exit /b %errorlevel%
