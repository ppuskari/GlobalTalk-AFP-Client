[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [string]$Repo = 'C:\AppleIIgsDev\GlobalTalk-AFP-Client',
    [string]$Remote = 'origin',
    [string]$Branch = 'integration/rfork-r3-20260906'
)

$ErrorActionPreference = 'Stop'

Push-Location -LiteralPath $Repo
try {
    & git rev-parse --is-inside-work-tree *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Not inside a Git repository: $Repo"
    }

    $Dirty = @(& git status --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw 'git status failed.'
    }
    if ($Dirty.Count -ne 0) {
        Write-Host 'Working tree has local changes. Nothing was modified.'
        & git status --short
        throw 'Commit, stash manually, or move those changes before syncing.'
    }

    $Top = (& git rev-parse --show-toplevel).Trim()
    Write-Host "Repository: $Top"
    Write-Host "Remote:     $Remote"
    Write-Host "Branch:     $Branch"
    Write-Host ''

    & git config --get "remote.$Remote.url"
    if ($LASTEXITCODE -ne 0) {
        throw "Git remote '$Remote' was not found."
    }

    & git fetch --prune $Remote
    if ($LASTEXITCODE -ne 0) {
        throw 'git fetch failed.'
    }

    & git show-ref --verify --quiet "refs/remotes/$Remote/$Branch"
    if ($LASTEXITCODE -ne 0) {
        throw "Remote branch $Remote/$Branch was not found."
    }

    & git show-ref --verify --quiet "refs/heads/$Branch"
    $HaveLocal = ($LASTEXITCODE -eq 0)

    if ($HaveLocal) {
        & git checkout $Branch
        if ($LASTEXITCODE -ne 0) { throw 'git checkout failed.' }

        & git merge --ff-only "$Remote/$Branch"
        if ($LASTEXITCODE -ne 0) {
            Write-Host ''
            Write-Host 'Fast-forward was not possible. No reset was performed.'
            & git status --short --branch
            & git log --oneline --decorate --graph --max-count=16 `
                "$Branch" "$Remote/$Branch"
            throw 'Local and remote history need review.'
        }
    }
    else {
        & git checkout -b $Branch --track "$Remote/$Branch"
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not create the local tracking branch.'
        }
    }

    Write-Host ''
    Write-Host 'PASS: Windows integration branch synchronized by fast-forward only.'
    & git status --short --branch
}
finally {
    Pop-Location
}
