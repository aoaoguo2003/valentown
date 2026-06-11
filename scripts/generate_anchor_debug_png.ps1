Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$jsonPath = Join-Path $root 'diagnostic_anchor_positions.json'
$pngPath = Join-Path $root 'diagnostic_anchor_positions.png'
$data = Get-Content -LiteralPath $jsonPath -Raw | ConvertFrom-Json

function New-ColorFromHex([string]$hex, [int]$alpha = 255) {
    $value = $hex.TrimStart('#')
    $r = [Convert]::ToInt32($value.Substring(0, 2), 16)
    $g = [Convert]::ToInt32($value.Substring(2, 2), 16)
    $b = [Convert]::ToInt32($value.Substring(4, 2), 16)
    return [System.Drawing.Color]::FromArgb($alpha, $r, $g, $b)
}

function Get-PoseColor([string]$pose) {
    if ($pose -eq 'lie') { return (New-ColorFromHex '#e85d9e') }
    if ($pose -eq 'sit') { return (New-ColorFromHex '#2f80ed') }
    return (New-ColorFromHex '#f2a93b')
}

$bitmap = New-Object System.Drawing.Bitmap([int]$data.width, [int]$data.height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$graphics.Clear((New-ColorFromHex '#9ddf74'))

$roadPen = New-Object System.Drawing.Pen((New-ColorFromHex '#f3e08b' 105), 18)
$roadPen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
$roadPen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
foreach ($road in $data.roads) {
    $graphics.DrawLine($roadPen, [float]$road.x1, [float]$road.y1, [float]$road.x2, [float]$road.y2)
}

$boxPen = New-Object System.Drawing.Pen((New-ColorFromHex '#516170'), 2)
$homeBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(46, 255, 255, 255))
$fontBold = New-Object System.Drawing.Font('Arial', 14, [System.Drawing.FontStyle]::Bold)
$fontSmall = New-Object System.Drawing.Font('Arial', 10, [System.Drawing.FontStyle]::Regular)
$fontTitle = New-Object System.Drawing.Font('Arial', 22, [System.Drawing.FontStyle]::Bold)
$fontLegend = New-Object System.Drawing.Font('Arial', 14, [System.Drawing.FontStyle]::Regular)
$textBrush = New-Object System.Drawing.SolidBrush((New-ColorFromHex '#111827'))

foreach ($homeBox in $data.homes) {
    $x = [float]($homeBox.x - ($homeBox.width / 2))
    $y = [float]($homeBox.y - ($homeBox.height / 2))
    $graphics.FillRectangle($homeBrush, $x, $y, [float]$homeBox.width, [float]$homeBox.height)
    $graphics.DrawRectangle($boxPen, $x, $y, [float]$homeBox.width, [float]$homeBox.height)
    $graphics.DrawString($homeBox.label, $fontBold, $textBrush, $x + 12, $y + 8)
}

foreach ($box in $data.publics) {
    $brush = New-Object System.Drawing.SolidBrush((New-ColorFromHex $box.fill 46))
    $x = [float]($box.x - ($box.width / 2))
    $y = [float]($box.y - ($box.height / 2))
    $graphics.FillRectangle($brush, $x, $y, [float]$box.width, [float]$box.height)
    $graphics.DrawRectangle($boxPen, $x, $y, [float]$box.width, [float]$box.height)
    $graphics.DrawString($box.label, $fontBold, $textBrush, $x + 12, $y + 8)
    $brush.Dispose()
}

$legendBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(225, 255, 255, 255))
$graphics.FillRectangle($legendBrush, 18, 752, 420, 116)
$graphics.DrawRectangle($boxPen, 18, 752, 420, 116)
$graphics.DrawString('Interaction Anchor Debug Map', $fontTitle, $textBrush, 36, 772)
$graphics.DrawString('orange = stand     blue = sit     pink = lie', $fontLegend, $textBrush, 36, 816)
$graphics.DrawString('Open the app with ?anchors=1 to see these points live.', $fontLegend, $textBrush, 36, 842)

$whitePen = New-Object System.Drawing.Pen([System.Drawing.Color]::White, 2)
$crossPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(145, 17, 24, 39), 1)
$labelBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(220, 255, 255, 255))
foreach ($marker in $data.markers) {
    $x = [float]$marker.x
    $y = [float]$marker.y
    $graphics.DrawLine($crossPen, $x - 11, $y, $x + 11, $y)
    $graphics.DrawLine($crossPen, $x, $y - 11, $x, $y + 11)
    $brush = New-Object System.Drawing.SolidBrush((Get-PoseColor $marker.pose))
    $graphics.FillEllipse($brush, $x - 7, $y - 7, 14, 14)
    $graphics.DrawEllipse($whitePen, $x - 7, $y - 7, 14, 14)
    $labelSize = $graphics.MeasureString($marker.label, $fontSmall)
    $graphics.FillRectangle($labelBrush, $x + 8, $y - 17, $labelSize.Width + 3, $labelSize.Height)
    $graphics.DrawString($marker.label, $fontSmall, $textBrush, $x + 9, $y - 18)
    $brush.Dispose()
}

$bitmap.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
$roadPen.Dispose()
$boxPen.Dispose()
$homeBrush.Dispose()
$legendBrush.Dispose()
$whitePen.Dispose()
$crossPen.Dispose()
$labelBrush.Dispose()
$textBrush.Dispose()
$fontBold.Dispose()
$fontSmall.Dispose()
$fontTitle.Dispose()
$fontLegend.Dispose()

Write-Output $pngPath
