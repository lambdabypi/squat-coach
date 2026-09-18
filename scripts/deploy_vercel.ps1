# Deploy the frontend to Vercel, pointed at a given backend.
#
#   .\scripts\deploy_vercel.ps1 -ApiUrl https://squat-coach-backend-xxxx.run.app
#
# Run `vercel login` first: it needs a browser, so it cannot be scripted.
#
# The important detail is ordering. NEXT_PUBLIC_* variables are inlined into the JavaScript at
# BUILD time, so the variable has to exist before the build runs. Deploying first and adding the
# variable afterwards leaves the shipped bundle calling localhost, and nothing about the deploy
# output tells you that. scripts/check_connection.py exists to catch exactly that mistake.

param(
    [Parameter(Mandatory = $true)][string]$ApiUrl,
    [string]$ProjectName = "squat-coach"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $root "frontend")

try {
    Write-Host "checking Vercel login..." -ForegroundColor Cyan
    $who = & vercel whoami 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Not logged in. Run 'vercel login' first (it opens a browser)." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "logged in as $who"

    Write-Host "`nlinking project '$ProjectName'..." -ForegroundColor Cyan
    & vercel link --yes --project $ProjectName 2>&1 | Select-Object -Last 3

    Write-Host "`nsetting NEXT_PUBLIC_API_URL for production..." -ForegroundColor Cyan
    # Remove any stale value first, or `env add` refuses and the old URL gets baked in.
    & vercel env rm NEXT_PUBLIC_API_URL production --yes 2>&1 | Out-Null
    $ApiUrl | & vercel env add NEXT_PUBLIC_API_URL production 2>&1 | Select-Object -Last 2

    Write-Host "`nbuilding and deploying..." -ForegroundColor Cyan
    $out = & vercel --prod --yes 2>&1
    $out | Select-Object -Last 12

    $url = ($out | Select-String -Pattern "https://[^\s]+\.vercel\.app" -AllMatches |
            ForEach-Object { $_.Matches.Value } | Select-Object -Last 1)
    if ($url) {
        Write-Host "`nfrontend: $url" -ForegroundColor Green
        Write-Host "`nNow do two things:" -ForegroundColor Yellow
        Write-Host "  1. Tighten CORS on the backend to this origin:"
        Write-Host "     gcloud run services update squat-coach-backend --region us-central1 ``"
        Write-Host "       --update-env-vars ALLOWED_ORIGINS=$url"
        Write-Host "  2. Verify the two are actually wired together:"
        Write-Host "     python scripts/check_connection.py $url $ApiUrl"
    }
}
finally {
    Pop-Location
}
