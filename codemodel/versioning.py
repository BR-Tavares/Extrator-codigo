"""Git como instrumento mínimo de permanência para o state.json.

Não é um wrapper genérico de git — só o suficiente pra dar ao state.json
um histórico versionado e reversível: `git init` se precisar, `git add` +
`git commit` a cada extração ou aprovação, e uma forma de ler a versão
anterior (`git show HEAD:...`) pra compor mensagens de commit automáticas
tipo "17 nodes (+2 desde o último snapshot)".

Deliberadamente sem nenhuma dependência (usa só `subprocess` + o binário
`git` do sistema). Se o git não estiver disponível, as funções aqui
devolvem `(False, motivo)` em vez de derrubar o resto do pipeline —
versionamento é um extra, não algo que deveria quebrar a extração/render.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional


def _run(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def is_git_available() -> bool:
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def ensure_repo(path: str) -> tuple[bool, str]:
    """Garante que o diretório do arquivo é um repositório git (roda `git
    init` se ainda não for). Devolve (ok, diretório_ou_erro)."""
    if not is_git_available():
        return False, "git não está disponível neste sistema"
    directory = str(Path(path).resolve().parent)
    check = _run(["rev-parse", "--is-inside-work-tree"], directory)
    if check.returncode != 0:
        init = _run(["init"], directory)
        if init.returncode != 0:
            return False, (init.stderr or init.stdout).strip()
    return True, directory


def snapshot(path: str, message: str) -> tuple[bool, str]:
    """`git add` + `git commit` do arquivo. Devolve (ok, mensagem)."""
    ok, directory_or_error = ensure_repo(path)
    if not ok:
        return False, directory_or_error
    directory = directory_or_error
    filename = Path(path).name

    add = _run(["add", filename], directory)
    if add.returncode != 0:
        return False, (add.stderr or add.stdout).strip()

    commit = _run(["commit", "-m", message], directory)
    if commit.returncode != 0:
        text = (commit.stdout + commit.stderr).lower()
        if "nothing to commit" in text or "nada a submeter" in text or "working tree clean" in text:
            return True, "nada mudou desde o último snapshot"
        return False, (commit.stderr or commit.stdout).strip()

    return True, f"commit criado: {message}"


def read_previous_node_count(path: str) -> Optional[int]:
    """Lê metadata.node_count da última versão *commitada* do arquivo (não
    a que está em disco agora), pra montar uma mensagem de commit tipo
    "17 nodes (+2)". Devolve None se não houver commit anterior ou git
    não estiver disponível — quem chama trata isso com uma mensagem genérica."""
    ok, directory_or_error = ensure_repo(path)
    if not ok:
        return None
    directory = directory_or_error
    filename = Path(path).name
    result = _run(["show", f"HEAD:{filename}"], directory)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        return data.get("metadata", {}).get("node_count")
    except (json.JSONDecodeError, AttributeError):
        return None


def auto_message(path: str, node_count: int, label: str = "extract") -> str:
    previous = read_previous_node_count(path)
    if previous is None:
        return f"{label}: {node_count} nodes"
    delta = node_count - previous
    sign = "+" if delta >= 0 else ""
    return f"{label}: {node_count} nodes ({sign}{delta} desde o último snapshot)"
