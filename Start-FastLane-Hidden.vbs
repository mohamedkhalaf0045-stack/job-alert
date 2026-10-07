Set shell  = CreateObject("WScript.Shell")
Set fso    = CreateObject("Scripting.FileSystemObject")
scriptDir  = fso.GetParentFolderName(WScript.ScriptFullName)
script     = scriptDir & "\cloud\fastlane.py"
shell.CurrentDirectory = scriptDir
' pythonw = no console window at all; fastlane.py itself keeps a single instance.
shell.Run "pythonw.exe """ & script & """ --loop 90", 0, False
