# Startup script for Granum with OSRM (Docker) on Windows

Write-Host "Starting Granum with OSRM Integration..." -ForegroundColor Cyan

# Check if OSRM data exists
if (-not (Test-Path "data/osrm")) {
    Write-Host "Warning: OSRM data directory not found in 'data/osrm'." -ForegroundColor Yellow
    Write-Host "Please run 'python scripts/setup_osrm.py' first to download and prepare the map data." -ForegroundColor Yellow
    Write-Host "Proceeding anyway (application might start, but OSRM routing will fail)..." -ForegroundColor DarkGray
    Start-Sleep -Seconds 3
}

# Check for Docker
if (-not (Get-Command "docker" -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Docker is not installed or not in PATH." -ForegroundColor Red
    Exit
}

# Run Docker Compose
Write-Host "Launching containers..." -ForegroundColor Cyan
docker-compose up --build

Write-Host "Application stopped." -ForegroundColor Cyan
