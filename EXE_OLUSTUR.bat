@echo off
cd /d %~dp0
where py >nul 2>nul
if errorlevel 1 (
  echo Python bulunamadi. EXE'yi GitHub Actions ile olusturmak icin KULLANIM.txt dosyasini oku.
  pause
  exit /b 1
)
py -3.12 -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pyinstaller --noconfirm --clean --onefile --name FlashscoreAnalyzer --collect-all selenium --hidden-import=waitress app.py
echo.
echo Hazir: dist\FlashscoreAnalyzer.exe
pause
