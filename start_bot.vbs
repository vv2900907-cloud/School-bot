Set WShell = CreateObject("WScript.Shell")
WShell.Run "cmd.exe /c cd /d C:\bot && py bot.py", 0, False
