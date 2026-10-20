# SPDX-License-Identifier: GPL-3.0-or-later
# The JERONIX bash prompt. Sourced from ~/.bashrc (the JERONIX user setup adds
# the line, between "JERONIX prompt" markers; remove them to go back).
#
#   jero@laptop ~/Projects
#   ❯
#
# Two lines, so long paths never squeeze the command. Colors are the
# 256-color JERONIX blue and ivory, which every terminal and the Linux
# console understand; plain text when colors are not available.

case $- in
    *i*) ;;
    *) return 0 ;;
esac
[ -n "${BASH_VERSION:-}" ] || return 0

__jeronix_prompt() {
    local symbol='>' blue='' text='' reset='' title=''
    case "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" in
        *UTF-8*|*utf8*|*UTF8*|*utf-8*) symbol='❯' ;;
    esac
    if [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ] 2>/dev/null; then
        blue='\[\e[1;38;5;75m\]'
        text='\[\e[38;5;254m\]'
        reset='\[\e[0m\]'
    fi
    case "$TERM" in
        xterm*|*-256color|vte*) title='\[\e]0;\u@\h: \w\a\]' ;;
    esac
    PS1="${title}${debian_chroot:+($debian_chroot) }${blue}\u@\h${reset} ${text}\w${reset}\n${blue}${symbol}${reset} "
}

__jeronix_prompt
unset -f __jeronix_prompt
