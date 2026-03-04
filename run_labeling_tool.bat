@echo off
cd /d "%~dp0"
echo Installing dependencies...
pip install -r requirements.txt --quiet
echo Starting Labeling Tool...
python labeling_tool.py
pause
