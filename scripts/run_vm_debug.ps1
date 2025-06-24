param(
    [ValidateSet('docker','vagrant','auto')]
    [string]$Prefer = 'auto',
    [switch]$Code
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PythonScript = Join-Path $ScriptDir 'run_vm_debug.py'

$ArgsList = @()
if ($Prefer -ne 'auto') { $ArgsList += '--prefer'; $ArgsList += $Prefer }
if ($Code) { $ArgsList += '--code' }

python $PythonScript @ArgsList
