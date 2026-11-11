"""Shell completion scripts, generated from the argparse parser so they never drift."""

from __future__ import annotations

import argparse

SHELLS = ("bash", "zsh", "fish")


def _commands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _options(sub: argparse.ArgumentParser) -> list[argparse.Action]:
    return [a for a in sub._actions if a.option_strings]


def _flags(sub: argparse.ArgumentParser) -> list[str]:
    out: list[str] = []
    for action in _options(sub):
        out.extend(action.option_strings)
    return out


def _quote(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _bash(prog: str, cmds: dict[str, argparse.ArgumentParser]) -> str:
    fn = "_" + prog
    lines = [f"# bash completion for {prog}", f"{fn}() {{",
             '    local cur prev cmd i', '    cur="${COMP_WORDS[COMP_CWORD]}"',
             '    prev="${COMP_WORDS[COMP_CWORD-1]}"', '    cmd=""',
             '    for ((i=1; i<COMP_CWORD; i++)); do',
             '        case "${COMP_WORDS[i]}" in',
             "            " + "|".join(cmds) + ') cmd="${COMP_WORDS[i]}"; break;;',
             "        esac", "    done",
             '    if [ -z "$cmd" ]; then',
             f'        COMPREPLY=( $(compgen -W "{" ".join(cmds)} --help --version" -- "$cur") )',
             "        return", "    fi",
             '    case "$cmd:$prev" in']
    for name, sub in cmds.items():
        for action in _options(sub):
            if action.choices:
                words = " ".join(str(c) for c in action.choices)
                pat = "|".join(f"{name}:{o}" for o in action.option_strings)
                lines.append(f'        {pat}) COMPREPLY=( $(compgen -W "{words}" -- "$cur") ); return;;')
    lines += ["    esac", '    case "$cmd" in']
    for name, sub in cmds.items():
        flags = " ".join(_flags(sub))
        lines.append(f"        {name}) COMPREPLY=( $(compgen -W \"{flags}\" -- \"$cur\") $(compgen -f -- \"$cur\") );;")
    lines += ["    esac", "}", f"complete -o filenames -F {fn} {prog}", ""]
    return "\n".join(lines)


def _zsh(prog: str, cmds: dict[str, argparse.ArgumentParser], helps: dict[str, str]) -> str:
    lines = [f"#compdef {prog}", f"_{prog}() {{", "    local -a commands",
             "    commands=("]
    for name, sub in cmds.items():
        lines.append(f"        {_quote(name + ':' + helps.get(name, name).replace(':', ' '))}")
    lines += ["    )", "    if (( CURRENT == 2 )); then",
              "        _describe 'command' commands", "        return", "    fi",
              '    case "$words[2]" in']
    for name, sub in cmds.items():
        specs = []
        for action in _options(sub):
            if action.choices:
                words = " ".join(str(c) for c in action.choices)
                tail = f":value:({words})"
            elif action.nargs == 0:
                tail = ""
            else:
                tail = ":value:"
            desc = (action.help or "").replace("'", "").replace("[", "(").replace("]", ")")
            for opt in action.option_strings:
                specs.append(_quote(f"{opt}[{desc}]{tail}"))
        specs.append("'*:file:_files'")
        lines.append(f"        {name}) _arguments " + " ".join(specs) + " ;;")
    lines += ["    esac", "}", f'_{prog} "$@"', ""]
    return "\n".join(lines)


def _help_map(parser: argparse.ArgumentParser) -> dict[str, str]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return {a.dest: a.help or "" for a in action._choices_actions}
    return {}


def _fish(prog: str, cmds: dict[str, argparse.ArgumentParser]) -> str:
    lines = [f"# fish completion for {prog}"]
    for name in cmds:
        lines.append(f"complete -c {prog} -n '__fish_use_subcommand' -a {name}")
    for name, sub in cmds.items():
        for action in _options(sub):
            parts = [f"complete -c {prog} -n '__fish_seen_subcommand_from {name}'"]
            for opt in action.option_strings:
                if opt.startswith("--"):
                    parts.append(f"-l {opt[2:]}")
                else:
                    parts.append(f"-s {opt[1:]}")
            if action.choices:
                parts.append("-x -a " + _quote(" ".join(str(c) for c in action.choices)))
            elif action.nargs != 0:
                parts.append("-r")
            lines.append(" ".join(parts))
    lines.append("")
    return "\n".join(lines)


def generate(shell: str, parser: argparse.ArgumentParser, prog: str) -> str:
    if shell not in SHELLS:
        raise ValueError(f"unsupported shell: {shell}")
    cmds = {n: s for n, s in _commands(parser).items() if n != "completion"}
    if shell == "zsh":
        return _zsh(prog, cmds, _help_map(parser))
    return (_bash if shell == "bash" else _fish)(prog, cmds)
