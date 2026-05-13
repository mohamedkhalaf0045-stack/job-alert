Set shell  = CreateObject("WScript.Shell")
Set fso    = CreateObject("Scripting.FileSystemObject")
scriptDir  = fso.GetParentFolderName(WScript.ScriptFullName)
guiPath    = scriptDir & "\linkedin-job-alert.ps1"
shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & guiPath & """", 0, False
