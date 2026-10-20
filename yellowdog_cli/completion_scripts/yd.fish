# Fish completion for the YellowDog CLI's yd command, printed by
# 'yd completion fish'. Load it from ~/.config/fish/config.fish with:
#
#   yd completion fish | source
#
# or, to complete the names and IDs of what is on the Platform too:
#
#   yd completion fish --names | source
#
# Each Tab asks 'yd completion --complete' what completes the current word
# ('--complete --names' when the script was printed with '--names').

function __yd_completion
    # '-x' (fish 3.8 and later) or '-o' (earlier): the words before the
    # cursor, unquoted; an empty current word is passed as no word at all
    set -l words (commandline -xpc 2>/dev/null; or commandline -opc)
    set -l current (commandline -ct)
    set -l reply (yd completion --complete fish (count $words) $words $current 2>/dev/null)
    or return
    switch "$reply[1]"
        case files
            __fish_complete_path "$current"
        case dirs
            __fish_complete_directories "$current"
        case values
            if test (count $reply) -gt 1
                printf '%s\n' $reply[2..-1]
            end
    end
end

complete --command yd --no-files --arguments '(__yd_completion)'
