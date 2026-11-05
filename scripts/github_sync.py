#!/usr/bin/env python3
"""Push the current branch using the local token, without persisting credentials."""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://github.com/ronnie-alfaro/artemis_whatsapp_3p_platform.git'


def main():
    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        for line in (ROOT / '.env').read_text().splitlines():
            key, sep, value = line.strip().removeprefix('export ').partition('=')
            if sep and key.strip() == 'GITHUB_TOKEN':
                token = value.strip().strip('\"\'')
    if not token:
        raise SystemExit('Falta GITHUB_TOKEN en el entorno o .env')
    git = ['git', '-c', f'safe.directory={ROOT}']
    branch = subprocess.check_output(git + ['branch', '--show-current'], cwd=ROOT, text=True).strip()
    if not branch:
        raise SystemExit('HEAD separado: selecciona una rama antes de sincronizar')
    with tempfile.TemporaryDirectory(prefix='artemis-git-') as directory:
        helper = Path(directory) / 'askpass'
        helper.write_text('#!/bin/sh\ncase "$1" in\n*Username*) printf "%s\\n" x-access-token ;;\n*) printf "%s\\n" "$GITHUB_TOKEN" ;;\nesac\n')
        helper.chmod(0o700)
        env = dict(os.environ, GITHUB_TOKEN=token, GIT_ASKPASS=str(helper), GIT_TERMINAL_PROMPT='0')
        subprocess.run(git + ['-c', 'credential.helper=', 'push', URL, f'HEAD:refs/heads/{branch}'], cwd=ROOT, env=env, check=True)


if __name__ == '__main__':
    main()
