param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ArgsList
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$PythonDir = Join-Path $ScriptDir '..\python'
$PythonScript = Join-Path $PythonDir 'run_plugin_preview.py'

python $PythonScript @ArgsList

