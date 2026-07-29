@echo off
rem まあ丸 客户端启动器：无控制台黑窗，直接出面板窗口
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" "maamaru_app.py"
