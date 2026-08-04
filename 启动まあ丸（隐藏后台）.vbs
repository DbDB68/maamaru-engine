' Hidden launcher. Keep this file ASCII for Windows Script Host compatibility.
' Use python.exe because pythonw has no stderr stream.
Set sh  = CreateObject("Wscript.Shell")
scriptDir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\") - 1)
sh.CurrentDirectory = scriptDir

sh.Environment("PROCESS")("PYTHONUTF8") = "1"
sh.Run """.venv\Scripts\python.exe"" ""maamaru_app.py""", 0, False
