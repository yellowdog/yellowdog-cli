# PowerShell completion for the YellowDog CLI's yd command, printed by
# 'yd completion powershell'. Load it from your $PROFILE with:
#
#   yd completion powershell | Out-String | Invoke-Expression
#
# Each Tab asks 'yd completion --complete' what completes the current word.

Register-ArgumentCompleter -Native -CommandName @('yd', 'yd.exe') -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    $words = @()
    foreach ($element in $commandAst.CommandElements) {
        if ($element.Extent.EndOffset -ge $cursorPosition) { break }
        if ($element -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
            $words += $element.Value
        } else {
            $words += $element.Extent.Text
        }
    }
    $index = $words.Count
    if ($wordToComplete) { $words += $wordToComplete }
    $reply = @(& yd completion --complete powershell $index @words 2>$null)
    if ($reply.Count -eq 0 -or $reply[0] -ne 'values') { return }
    foreach ($line in ($reply | Select-Object -Skip 1)) {
        $value, $description = $line -split "`t", 2
        if (-not $description) { $description = $value }
        $kind = if ($value.StartsWith('-')) { 'ParameterName' } else { 'ParameterValue' }
        [System.Management.Automation.CompletionResult]::new($value, $value, $kind, $description)
    }
}
