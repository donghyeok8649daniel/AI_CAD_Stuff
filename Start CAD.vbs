Option Explicit
Dim fso, shell, root, candidate, python
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
python = root & "\.venv\Scripts\pythonw.exe"
If Not fso.FileExists(python) Then
  candidate = fso.GetAbsolutePathName(root & "\..\..\work\.venv\Scripts\pythonw.exe")
  If fso.FileExists(candidate) Then python = candidate
End If
If Not fso.FileExists(python) Then
  MsgBox "Run setup.ps1 in the CAD folder first. See README.md.", vbExclamation, "Prompt CAD Studio"
  WScript.Quit 1
End If
shell.CurrentDirectory = root
shell.Run Chr(34) & python & Chr(34) & " " & Chr(34) & root & "\native_desktop.py" & Chr(34), 0, False
