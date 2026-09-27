@echo off
REM Run sciscrap from this folder without activating the venv.
"%~dp0.venv\Scripts\python.exe" -m sciscrap %*
