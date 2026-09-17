Option Explicit

' Double-click launcher for the desktop monitor plus a temporary HTTPS tunnel.
' Both the monitor and cloudflared run without opening a persistent console.
Dim fileSystem, shell, projectDir, configPath, sshHost, commandLine
Set fileSystem = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectDir = fileSystem.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = projectDir
shell.Environment("Process")("PYTHONPATH") = projectDir & "\server"
configPath = projectDir & "\monitor.config.json"

If fileSystem.FileExists(configPath) Then
    commandLine = "py.exe -3 -m monitorctl_py desktop --config " & Quote(configPath) & " --cloudflare"
Else
    sshHost = shell.Environment("Process")("TRAINING_MONITOR_SSH")
    If Len(Trim(sshHost)) = 0 Then
        MsgBox "Create monitor.config.json and fill in ssh first." & vbCrLf & _
               "For a temporary connection, set TRAINING_MONITOR_SSH." & vbCrLf & vbCrLf & _
               "This launcher also requires cloudflared in PATH.", _
               vbInformation, "Training Monitor"
        WScript.Quit 1
    End If
    commandLine = "py.exe -3 -m monitorctl_py desktop --ssh " & Quote(sshHost) & " --cloudflare"
End If

' WindowStyle 0 hides the Python console; False keeps the GUI process running.
shell.Run commandLine, 0, False

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
