param(
    [Parameter(Mandatory = $true)]
    [string]$OutFile
)

Add-Type -AssemblyName System.Windows.Forms

$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$owner.Opacity = 0
$owner.Width = 1
$owner.Height = 1
$owner.StartPosition = "CenterScreen"
$owner.Show()
$owner.Activate()

$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = "Select a video"
$dialog.Filter = "Video|*.mp4;*.mov;*.mkv;*.avi;*.webm;*.m4v;*.ogv;*.wmv;*.mpeg;*.mpg"
$dialog.CheckFileExists = $true
$dialog.Multiselect = $false
$dialog.RestoreDirectory = $true

$result = $dialog.ShowDialog($owner)
$owner.Close()
$owner.Dispose()

$text = ""
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    $text = $dialog.FileName
}

$utf8 = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($OutFile, $text, $utf8)
