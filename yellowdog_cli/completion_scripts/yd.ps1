# PowerShell completion for the YellowDog CLI's yd command, printed by
# 'yd completion powershell'. Load it from your $PROFILE with:
#
#   yd completion powershell | Out-String | Invoke-Expression
#
# or, to complete the names and IDs of what is on the Platform too:
#
#   yd completion powershell --names | Out-String | Invoke-Expression
#
# Each Tab asks 'yd completion --complete' what completes the current word
# ('--complete --names' when the script was printed with '--names').

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
    if ($reply.Count -eq 0) { return }
    # A file or directory after an '--option=': PowerShell's own completion,
    # which answering nothing falls back to, would take the option for part
    # of the path, so the part after '=' is completed here
    if ($reply[0] -in @('files', 'dirs') -and $wordToComplete -match '^(-[^=]*=)(.*)$') {
        $option = $Matches[1]
        foreach ($found in [System.Management.Automation.CompletionCompleters]::CompleteFilename($Matches[2])) {
            if ($reply[0] -eq 'dirs' -and $found.ResultType -ne 'ProviderContainer') { continue }
            [System.Management.Automation.CompletionResult]::new(
                $option + $found.CompletionText, $found.ListItemText, $found.ResultType, $found.ToolTip)
        }
        return
    }
    if ($reply[0] -ne 'values') { return }
    foreach ($line in ($reply | Select-Object -Skip 1)) {
        $value, $description = $line -split "`t", 2
        if (-not $description) { $description = $value }
        $kind = if ($value.StartsWith('-')) { 'ParameterName' } else { 'ParameterValue' }
        [System.Management.Automation.CompletionResult]::new($value, $value, $kind, $description)
    }
}
