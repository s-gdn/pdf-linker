@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -c "import PySide6, pymupdf, openpyxl, xlrd, numpy, onnxruntime, tokenizers, rapidfuzz" >nul 2>&1
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -e .
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe scripts\prepare_models.py
if errorlevel 1 goto failed
start "" .venv\Scripts\pythonw.exe -m pdflinker
exit /b
:failed
echo Setup failed. Check that Python 3.11 or later is installed and internet access is available.
pause
