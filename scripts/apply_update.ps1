param(
    [Parameter(Mandatory = $true)][int]$ParentPid,
    [Parameter(Mandatory = $true)][string]$AppDir,
    [Parameter(Mandatory = $true)][string]$PayloadDir,
    [Parameter(Mandatory = $true)][string]$Version
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$AppDir = [System.IO.Path]::GetFullPath($AppDir)
$PayloadDir = [System.IO.Path]::GetFullPath($PayloadDir)
$StateDir = Join-Path $env:LOCALAPPDATA "EOIRTabs"
$LogPath = Join-Path $StateDir "update.log"
$ErrorMarker = Join-Path $AppDir "_update\last_error.txt"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir = Join-Path $StateDir "backups\$Timestamp"

New-Item -ItemType Directory -Force -Path $StateDir | Out-Null

function Write-UpdateLog([string]$Message) {
    $line = "$(Get-Date -Format o) $Message"
    Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    Write-Host $Message
}

function Assert-SafeRelativePath([string]$RelativePath) {
    if ([string]::IsNullOrWhiteSpace($RelativePath) -or [System.IO.Path]::IsPathRooted($RelativePath)) {
        throw "Ruta inválida en el manifiesto: $RelativePath"
    }
    $normalized = $RelativePath.Replace("/", "\")
    $parts = $normalized.Split("\")
    $protectedRoots = @(".git", "_update", "case_store", "firmas", "input", "output", "usuarios", "venv")
    $protectedFiles = @("firebase-api-key.txt", "firebase-project-id.txt")
    if ($parts.Count -gt 0 -and $protectedRoots -contains $parts[0].ToLowerInvariant()) {
        throw "El manifiesto intenta modificar datos locales: $RelativePath"
    }
    $leaf = [System.IO.Path]::GetFileName($normalized).ToLowerInvariant()
    if ($protectedFiles -contains $leaf -or $leaf.StartsWith(".env")) {
        throw "El manifiesto intenta modificar configuración local: $RelativePath"
    }
    foreach ($part in $parts) {
        if ($part -eq ".." -or $part -eq "." -or $part.Contains(":")) {
            throw "Ruta insegura en el manifiesto: $RelativePath"
        }
    }
    $full = [System.IO.Path]::GetFullPath((Join-Path $AppDir $normalized))
    $prefix = $AppDir.TrimEnd("\") + "\"
    if (-not $full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Ruta fuera de la aplicación: $RelativePath"
    }
}

function Start-EoirApp {
    $StartBat = Join-Path $AppDir "iniciar.bat"
    if (Test-Path -LiteralPath $StartBat) {
        Start-Process -FilePath $StartBat -WorkingDirectory $AppDir
    }
}

Write-UpdateLog "Esperando que se cierre la versión anterior..."
try {
    Wait-Process -Id $ParentPid -ErrorAction SilentlyContinue
} catch {
    # El proceso ya terminó.
}

$Touched = New-Object System.Collections.Generic.List[string]
$Existed = @{}

try {
    $ManifestPath = Join-Path $PayloadDir "update-files.json"
    $VersionPath = Join-Path $PayloadDir "version.json"
    if (-not (Test-Path -LiteralPath $ManifestPath) -or -not (Test-Path -LiteralPath $VersionPath)) {
        throw "El paquete preparado no contiene sus manifiestos."
    }
    $Manifest = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $VersionInfo = Get-Content -LiteralPath $VersionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Manifest.version -ne $Version -or $VersionInfo.version -ne $Version) {
        throw "La versión preparada no coincide con la versión solicitada."
    }

    $NewFiles = @($Manifest.files | ForEach-Object { [string]$_ })
    if ($NewFiles.Count -eq 0) {
        throw "El manifiesto no contiene archivos."
    }
    foreach ($relative in $NewFiles) {
        Assert-SafeRelativePath $relative
        $source = Join-Path $PayloadDir ($relative.Replace("/", "\"))
        if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
            throw "Falta el archivo del paquete: $relative"
        }
    }

    # Instalar primero las dependencias nuevas. Si falla, el código instalado
    # todavía no se ha tocado y la versión anterior puede arrancar normalmente.
    $PythonExe = Join-Path $AppDir "venv\Scripts\python.exe"
    $Requirements = Join-Path $PayloadDir "requirements.txt"
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        throw "No existe el entorno virtual. Ejecuta instalar.bat y vuelve a intentarlo."
    }
    Write-UpdateLog "Verificando dependencias de la nueva versión..."
    & $PythonExe -m pip install --disable-pip-version-check -r $Requirements
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudieron instalar las dependencias de la actualización."
    }

    $OldFiles = @()
    $OldManifestPath = Join-Path $AppDir "update-files.json"
    if (Test-Path -LiteralPath $OldManifestPath) {
        try {
            $OldManifest = Get-Content -LiteralPath $OldManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $OldFiles = @($OldManifest.files | ForEach-Object { [string]$_ })
        } catch {
            $OldFiles = @()
        }
    }

    $AllTouched = @($NewFiles + $OldFiles | Sort-Object -Unique)
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    foreach ($relative in $AllTouched) {
        Assert-SafeRelativePath $relative
        $destination = Join-Path $AppDir ($relative.Replace("/", "\"))
        $exists = Test-Path -LiteralPath $destination -PathType Leaf
        $Existed[$relative] = $exists
        $Touched.Add($relative)
        if ($exists) {
            $backup = Join-Path $BackupDir ($relative.Replace("/", "\"))
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
            Copy-Item -LiteralPath $destination -Destination $backup -Force
        }
    }

    Write-UpdateLog "Aplicando la versión $Version..."
    foreach ($relative in $NewFiles) {
        $source = Join-Path $PayloadDir ($relative.Replace("/", "\"))
        $destination = Join-Path $AppDir ($relative.Replace("/", "\"))
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
        $temporary = "$destination.eoir-update-new"
        Copy-Item -LiteralPath $source -Destination $temporary -Force
        if (Test-Path -LiteralPath $destination -PathType Leaf) {
            [System.IO.File]::Replace($temporary, $destination, $null)
        } else {
            [System.IO.File]::Move($temporary, $destination)
        }
    }

    $NewSet = @{}
    foreach ($relative in $NewFiles) { $NewSet[$relative] = $true }
    foreach ($relative in $OldFiles) {
        if (-not $NewSet.ContainsKey($relative)) {
            $obsolete = Join-Path $AppDir ($relative.Replace("/", "\"))
            if (Test-Path -LiteralPath $obsolete -PathType Leaf) {
                Remove-Item -LiteralPath $obsolete -Force
            }
        }
    }

    Remove-Item -LiteralPath $ErrorMarker -Force -ErrorAction SilentlyContinue
    Write-UpdateLog "Actualización completada. Reiniciando la aplicación..."
    Start-EoirApp
    exit 0
} catch {
    $message = $_.Exception.Message
    Write-UpdateLog "ERROR: $message"
    Write-UpdateLog "Restaurando la versión anterior..."
    foreach ($relative in $Touched) {
        try {
            $destination = Join-Path $AppDir ($relative.Replace("/", "\"))
            $backup = Join-Path $BackupDir ($relative.Replace("/", "\"))
            if ($Existed[$relative] -and (Test-Path -LiteralPath $backup -PathType Leaf)) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination) | Out-Null
                Copy-Item -LiteralPath $backup -Destination $destination -Force
            } elseif (-not $Existed[$relative] -and (Test-Path -LiteralPath $destination -PathType Leaf)) {
                Remove-Item -LiteralPath $destination -Force
            }
        } catch {
            Write-UpdateLog "No se pudo restaurar $relative"
        }
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ErrorMarker) | Out-Null
    Set-Content -LiteralPath $ErrorMarker -Value $message -Encoding UTF8
    Write-UpdateLog "La actualización falló. Se reiniciará la versión anterior."
    Start-EoirApp
    exit 1
}
