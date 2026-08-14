@echo off

chcp 65001 >nul

title 漫畫標號器

set "TARGET_DIR=%~f1"
if not defined TARGET_DIR set "TARGET_DIR=%~dp0"

cd /d "%TARGET_DIR%"

echo ===============================
echo 檢查舊伺服器...
echo ===============================

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    echo 發現舊進程 PID: %%a
    taskkill /PID %%a /F >nul 2>&1
)

echo.
echo 啟動中... 伺服器掛在此視窗，關閉請按 Ctrl+C
echo 網址: http://127.0.0.1:5000
echo.

python "%~dp0main.py" "%CD%"

echo.
pause >nul