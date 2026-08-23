@echo off
rem Download the Comic Text Detector ONNX model into .\models\
rem Source: BallonsTranslator / manga-image-translator official release.
chcp 65001 >nul
cd /d "%~dp0"

set "MODEL=models\comictextdetector.pt.onnx"
set "URL=https://github.com/zyddnys/manga-image-translator/releases/download/beta-0.3/comictextdetector.pt.onnx"

if exist "%MODEL%" (
    echo Model already exists: %CD%\%MODEL%
    pause
    exit /b 0
)

if not exist models mkdir models

echo Downloading CTD model (~90 MB) ...
echo   %URL%
curl.exe -L --fail --retry 3 --progress-bar -o "%MODEL%.part" "%URL%"
if errorlevel 1 (
    echo.
    echo [ERROR] Download failed. Check your network, or download manually:
    echo   %URL%
    echo then put the file at: %CD%\%MODEL%
    del "%MODEL%.part" >nul 2>&1
    pause
    exit /b 1
)

move /y "%MODEL%.part" "%MODEL%" >nul
echo.
echo Done: %CD%\%MODEL%
pause
