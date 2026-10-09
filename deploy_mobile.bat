@echo off
title Medi Hospital Platform - Mobile Deployment
echo Starting Medi Hospital Platform...
echo.
if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe deploy.py
) else (
    python deploy.py
)
pause
