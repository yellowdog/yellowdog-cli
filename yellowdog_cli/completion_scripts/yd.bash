# Bash completion for the YellowDog CLI's yd command, printed by
# 'yd completion bash'. Load it from ~/.bashrc with:
#
#   eval "$(yd completion bash)"
#
# or, to complete the names and IDs of what is on the Platform too:
#
#   eval "$(yd completion bash --names)"
#
# Each Tab asks 'yd completion --complete' what completes the current word
# ('--complete --names' when the script was printed with '--names').

_yd_completion() {
    local cur=${COMP_WORDS[COMP_CWORD]}
    local reply mode line
    # IFS is left alone until the words are passed: bash 3.2 joins an array
    # slice into one word when IFS holds no space
    reply=$(yd completion --complete bash "$COMP_CWORD" "${COMP_WORDS[@]:0:COMP_CWORD+1}" 2>/dev/null) || return 0
    mode=${reply%%$'\n'*}
    COMPREPLY=()
    case $mode in
        files|dirs)
            type compopt &>/dev/null && compopt -o filenames
            local IFS=$'\n'
            if [[ $mode == files ]]; then
                COMPREPLY=($(compgen -f -- "$cur"))
            else
                COMPREPLY=($(compgen -d -- "$cur"))
            fi
            ;;
        values)
            [[ $reply == *$'\n'* ]] || return 0
            while IFS= read -r line; do
                COMPREPLY+=("${line%%$'\t'*}")
            done <<< "${reply#*$'\n'}"
            ;;
    esac
    return 0
}

complete -F _yd_completion yd
