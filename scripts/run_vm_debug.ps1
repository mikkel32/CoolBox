param(
    [ValidateSet('docker','vagrant','auto')]
    [string]$Prefer = 'auto',
    [switch]$Code,
    [int]$Port = 5678,
    [switch]$List,
    [switch]$SkipDeps
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PythonScript = Join-Path $ScriptDir 'run_vm_debug.py'

$ArgsList = @()
if ($Prefer -ne 'auto') { $ArgsList += '--prefer'; $ArgsList += $Prefer }
if ($Code) { $ArgsList += '--code' }
if ($Port -ne 5678) { $ArgsList += '--port'; $ArgsList += $Port }
if ($List) { $ArgsList += '--list' }
if ($SkipDeps) { $ArgsList += '--skip-deps' }

python $PythonScript @ArgsList
