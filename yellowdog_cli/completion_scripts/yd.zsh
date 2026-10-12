# Zsh completion for the YellowDog CLI's yd command, printed by
# 'yd completion zsh'. Load it from ~/.zshrc with:
#
#   eval "$(yd completion zsh)"
#
# Each Tab asks 'yd completion --complete' what completes the current word.

_yd_completion() {
    local reply mode line
    local -a lines candidates
    reply=$(yd completion --complete zsh $(( CURRENT - 1 )) "${(@)words[1,CURRENT]}" 2>/dev/null) || return 1
    lines=("${(@f)reply}")
    mode=${lines[1]}
    case $mode in
        files) _files ;;
        dirs) _files -/ ;;
        values)
            for line in "${(@)lines[2,-1]}"; do
                if [[ $line == *$'\t'?* ]]; then
                    candidates+=("${${line%%$'\t'*}//:/\\:}:${line#*$'\t'}")
                else
                    candidates+=("${${line%%$'\t'*}//:/\\:}")
                fi
            done
            (( ${#candidates} )) && _describe -t values 'value' candidates
            ;;
    esac
}

if ! (( $+functions[compdef] )); then
    autoload -Uz compinit && compinit
fi
compdef _yd_completion yd
