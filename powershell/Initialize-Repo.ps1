# PowerShell 5.1+
# Put the starter package at C:\AppleIIgsDev\GlobalTalk-AFP-Client,
# then run this script from that directory.

$Base = 'C:\AppleIIgsDev'
$Name = 'GlobalTalk-AFP-Client'
$Repo = Join-Path $Base $Name

if (-not (Test-Path $Base)) {
    throw "Base folder does not exist: $Base"
}

if (-not (Test-Path $Repo)) {
    New-Item -ItemType Directory -Path $Repo | Out-Null
}

Set-Location $Repo

if (-not (Test-Path '.git')) {
    git init
    git branch -M main
}

git add .
git commit -m "Initial AFP-over-DDP transport for Netatalk Client 0.9.5"

gh repo create ppuskari/GlobalTalk-AFP-Client `
    --public `
    --source . `
    --remote origin `
    --push
