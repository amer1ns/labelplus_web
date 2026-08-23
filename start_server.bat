@echo off

chcp 65001 >nul

title 漫畫標號器

set "TARGET_DIR=%~f1"
if not defined TARGET_DIR set "TARGET_DIR=%~dp0"

cd /d "%TARGET_DIR%"

echo ===============================
echo 檢查舊伺服器...
echo ===============================

REM 只清除殘留的 python 伺服器進程（佔用 5000 埠者），不影響其他軟體
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5000 ^| findstr LISTENING') do (
    tasklist /FI "PID eq %%a" | findstr /I "python.exe" >nul && (
        echo 發現殘留舊進程 PID: %%a，已清除
        taskkill /PID %%a /F >nul 2>&1
    )
)

echo.
echo 啟動中... 伺服器掛在此視窗，關閉請按 Ctrl+C
echo 網址: http://127.0.0.1:5000
echo （若 5000 埠被占用，會自動改用其他埠，請看視窗內的提示）
echo.

python "%~dp0main.py" "%CD%"

echo.
pause >nul
