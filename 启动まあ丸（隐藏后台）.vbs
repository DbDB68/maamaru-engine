' まあ丸 隐形启动器：不弹任何终端窗口，任务栏只有面板窗口
' 原理：wscript 以 0（完全隐藏）方式拉起 pythonw，进程只在后台跑
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("Wscript.Shell")
sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run """.venv\Scripts\pythonw.exe"" ""maamaru_app.py""", 0, False
