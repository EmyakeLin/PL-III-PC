$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$title = '光点计划 III'
$created = $false
# One auto-reset event both elects the owner and queues a launch during startup.
$hash = [Security.Cryptography.SHA256]::Create().ComputeHash(
    [Text.Encoding]::UTF8.GetBytes($env:PL3_ENTRY.ToLowerInvariant()))
$name = 'Local\PL3-' + [BitConverter]::ToString($hash)
$signal = [Threading.EventWaitHandle]::new($false, 'AutoReset', $name, [ref]$created)
if (!$created) {
    [void]$signal.Set()
    $signal.Dispose()
    return
}

function Open-Lobby {
    try { Start-Process $url }
    catch { [void][Windows.Forms.MessageBox]::Show("请在浏览器中打开 $url", $title) }
}

try {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $env:PL3_PYTHON
    $info.Arguments = '"' + $env:PL3_ENTRY + '" --serve'
    $info.WorkingDirectory = Split-Path $env:PL3_ENTRY
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardErrorEncoding = [Text.Encoding]::UTF8
    $worker = [Diagnostics.Process]::Start($info)
    $errors = $worker.StandardError.ReadToEndAsync()
    $url = $worker.StandardOutput.ReadLine()
    if ($url -notmatch '^http://127\.0\.0\.1:\d+/#desktop=[a-f0-9]{32}$') {
        throw "大厅启动失败。`n$($errors.GetAwaiter().GetResult())"
    }

    $tray = [Windows.Forms.NotifyIcon]::new()
    $tray.Icon = [Drawing.SystemIcons]::Application
    $tray.Text = $title
    $menu = [Windows.Forms.ContextMenuStrip]::new()
    [void]$menu.Items.Add('打开大厅', $null, { Open-Lobby })
    [void]$menu.Items.Add('退出游戏', $null, {
        if (!$worker.HasExited) {
            $worker.StandardInput.WriteLine('rooms')
            $count = [int]$worker.StandardOutput.ReadLine()
            if ($count -gt 0) {
                $choice = [Windows.Forms.MessageBox]::Show(
                    "退出将结束当前的 $count 个房间。确定退出游戏？", $title,
                    'YesNo', 'Warning', 'Button2')
                if ($choice -ne 'Yes') { return }
            }
        }
        [Windows.Forms.Application]::ExitThread()
    })
    $tray.ContextMenuStrip = $menu
    $tray.add_DoubleClick({ Open-Lobby })
    $timer = [Windows.Forms.Timer]::new()
    $timer.Interval = 250
    $timer.add_Tick({
        if ($worker.HasExited) {
            $timer.Stop()
            [void][Windows.Forms.MessageBox]::Show("大厅已停止。`n$($errors.Result)", $title)
            [Windows.Forms.Application]::ExitThread()
        } elseif ($signal.WaitOne(0)) { Open-Lobby }
    })
    $tray.Visible = $true
    $timer.Start()
    Open-Lobby
    [Windows.Forms.Application]::Run()
} catch {
    [void][Windows.Forms.MessageBox]::Show($_.Exception.Message, $title, 'OK', 'Error')
} finally {
    if ($timer) { $timer.Dispose() }
    if ($tray) { $tray.Dispose() }
    if ($menu) { $menu.Dispose() }
    if ($worker) {
        $worker.StandardInput.Close()
        $worker.WaitForExit()
        $worker.Dispose()
    }
    $signal.Dispose()
}
