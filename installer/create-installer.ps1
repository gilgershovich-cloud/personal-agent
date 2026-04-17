# יוצר installer מותאם אישית למשתמש חדש
# שימוש: .\create-installer.ps1 -Name "אמא" -Token "ima2024"

param(
    [Parameter(Mandatory=$true)]
    [string]$Name,

    [Parameter(Mandatory=$true)]
    [string]$Token
)

$template = Get-Content "$PSScriptRoot\install.ps1" -Raw
$customized = $template -replace "__TOKEN__", $Token

$outputFile = "$PSScriptRoot\install-$Name.ps1"
$customized | Out-File -FilePath $outputFile -Encoding UTF8

Write-Host ""
Write-Host "נוצר installer עבור: $Name" -ForegroundColor Green
Write-Host "קובץ: $outputFile" -ForegroundColor Cyan
Write-Host ""
Write-Host "שלח לאמא את ההוראות הבאות:" -ForegroundColor Yellow
Write-Host "----------------------------------------"
Write-Host "1. פתח PowerShell (חפש 'PowerShell' בתפריט התחל)"
Write-Host "2. הדבק ולחץ Enter:"
Write-Host ""
Write-Host "   Set-ExecutionPolicy -Scope CurrentUser Bypass -Force; irm 'https://personal-agent-q29j.onrender.com/installer/$Token' | iex" -ForegroundColor Cyan
Write-Host ""
Write-Host "----------------------------------------"
Write-Host ""
Write-Host "אחרי שהיא מריצה — הוסף אותה לשרת:" -ForegroundColor Yellow
Write-Host "הרץ: .\add-user.ps1 -Name '$Name' -Token '$Token'" -ForegroundColor Cyan
