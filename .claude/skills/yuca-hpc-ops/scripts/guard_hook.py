#!/usr/bin/env python3
"""Guardarraíl PreToolUse de Claude Code para operar en el cluster Yuca.

Lee el evento PreToolUse en stdin y decide:
  - deny : acción de nivel 3 (prohibida). Se bloquea y se le explica a Claude.
  - ask  : acción de nivel 2. Claude Code le pide confirmación a Owen.
  - nada : el comando sigue el flujo normal de permisos de Claude Code.

Diseño:
  * Falla cerrado: cualquier excepción interna produce `deny`.
  * Solo librería estándar; funciona en Windows, macOS y Linux.
  * Analiza tanto comandos locales como los que van dentro de `ssh yuca '...'`.
  * Es una red de seguridad basada en patrones, no un sandbox. Un comando que
    pasa este filtro no es automáticamente seguro.

Prueba manual:
  echo '{"tool_name":"Bash","tool_input":{"command":"ssh yuca rm -rf x"}}' | python guard_hook.py
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import socket
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuración del proyecto
# --------------------------------------------------------------------------- #
USER = "owen"
ACCOUNT = "p082"
PROJECT_ROOT = "/lustre/proyectos/p082"
REPO_REMOTE = PROJECT_ROOT + "/code"
ALLOWED_SSH_HOSTS = {"yuca", "yuca.unison.mx", "login-01"}

# Rutas de solo lectura (dataset crudo compartido).
READONLY = ("kaggle_data",)
# Rutas de otras personas.
FOREIGN = (PROJECT_ROOT + "/envs", PROJECT_ROOT + "/nllb", "p082/envs", "p082/nllb")
OTHER_HOMES = re.compile(r"/lustre/home/(?!" + re.escape(USER) + r"(/|$|['\"\s]))[\w.-]+")
# Archivos que protegen al propio guardarraíl.
SELF_PROTECTED = re.compile(
    r"\.claude[\\/](settings[^\\/]*\.json|hooks)|guard_hook\.py|check_slurm\.py|yuca-hpc-ops[\\/]",
    re.I,
)
SECRETS = re.compile(
    r"\.ssh[\\/]|authorized_keys|kaggle\.json|\.netrc|\.git-credentials|\.claude[\\/]\.credentials|"
    r"\.claude\.json|opencode[\\/]auth\.json|huggingface[\\/]token|\bhf_token\b|\.pypirc|"
    r"id_(rsa|ed25519|ecdsa)",
    re.I,
)
SHELL_RC = re.compile(r"\.(bashrc|bash_profile|profile|zshrc|condarc)\b")

HEAVY_PY = re.compile(r"(train|preprocess|prepro|convert|infer|predict|extract|finetune|fit|export)", re.I)
SKILL_SCRIPTS = re.compile(r"(yuca-hpc-ops[\\/]scripts|check_slurm\.py)")

ON_CLUSTER = socket.gethostname().startswith("login") or os.environ.get("YUCA_GUARD_ON_CLUSTER") == "1"
LOG_PATH = Path(os.environ.get("YUCA_GUARD_LOG", Path.home() / ".claude" / "yuca-guard.log"))

NO_EVADE = " No reformules el comando para esquivar esta regla; explícale a Owen qué querías hacer."

WRITE_VERBS = {"mv", "chmod", "chgrp", "chown", "setfacl", "truncate", "shred", "unlink",
               "touch", "mkdir", "ln", "tee", "dd", "install", "rmdir"}
COPY_VERBS = {"cp", "rsync", "scp"}
TRAVERSE_VERBS = {"find", "du", "tar", "rsync", "cp", "zip", "md5sum", "sha256sum", "wc", "grep", "rg"}
WRAPPERS = {"command", "builtin", "exec", "time", "stdbuf", "nice", "ionice", "env", "then", "do",
            "else", "elif", "if", "while", "until", "!", "{", "}"}
SSH_OPTS_WITH_VALUE = set("bcDEeFIiJLlmOopQRSWw")


class Verdict:
    def __init__(self) -> None:
        self.deny: list[str] = []
        self.ask: list[str] = []

    def d(self, msg: str) -> None:
        if msg not in self.deny:
            self.deny.append(msg)

    def a(self, msg: str) -> None:
        if msg not in self.ask:
            self.ask.append(msg)


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _norm(path: str) -> str:
    return path.replace("\\", "/")


def touches(args: list[str], markers) -> bool:
    return any(m in _norm(a) for a in args for m in markers)


def is_foreign(arg: str) -> bool:
    a = _norm(arg)
    return any(f in a for f in FOREIGN) or bool(OTHER_HOMES.search(a))


def is_project_toplevel(arg: str) -> bool:
    a = _norm(arg).rstrip("/")
    return bool(re.fullmatch(re.escape(PROJECT_ROOT) + r"(/[^/]+)?", a))


def non_flags(args: list[str]) -> list[str]:
    return [a for a in args if not a.startswith("-")]


def split_segments(cmd: str) -> list[str]:
    """Divide en subcomandos: ; && || | & salto de línea $( ` ( )."""
    parts = re.split(r"\|\||&&|(?<![>&<0-9])&(?![&>])|;|\||\n|\$\(|`|\(|\)", cmd)
    return [p for p in parts if p and p.strip()]


def tokenize(segment: str) -> list[str]:
    cleaned = segment.replace("'", " ").replace('"', " ")
    return cleaned.split()


def strip_wrappers(tokens: list[str]) -> list[str]:
    """Quita asignaciones VAR=x y envoltorios como `env`, `nice -n 5`, `timeout 60`."""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", t):
            i += 1
        elif t in WRAPPERS:
            i += 1
            if t in ("nice", "ionice") and i < len(tokens) and tokens[i] in ("-n", "-c"):
                i += 2
            elif t == "env":
                while i < len(tokens) and tokens[i].startswith("-"):
                    i += 1
        elif t == "timeout":
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
            i += 1  # duración
        else:
            break
    return tokens[i:]


# --------------------------------------------------------------------------- #
# Reglas globales (sobre el texto completo)
# --------------------------------------------------------------------------- #
GLOBAL_DENY = [
    (r"\bcurl\b[^\n|;]*(\s-[a-zA-Z]*k[a-zA-Z]*\b|--insecure)", "Desactivar TLS en curl (-k/--insecure)."),
    (r"--no-check-certificate", "Desactivar TLS en wget."),
    (r"NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0", "Desactivar TLS en Node."),
    (r"PYTHONHTTPSVERIFY\s*=\s*['\"]?0", "Desactivar TLS en Python."),
    (r"verify\s*=\s*False|_create_unverified_context|CERT_NONE", "Desactivar verificación TLS en Python."),
    (r"--trusted-host", "pip --trusted-host salta la verificación TLS."),
    (r"GIT_SSL_NO_VERIFY|sslVerify\s*=?\s*false", "Desactivar TLS en git."),
    (r"(CURL_CA_BUNDLE|REQUESTS_CA_BUNDLE|SSL_CERT_FILE)\s*=\s*(''|\"\"|\s|$)", "Vaciar el bundle de CAs."),
    (r"\b(curl|wget)\b[^\n;]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b", "Descargar y ejecutar sin revisar (curl | sh)."),
    (r"base64\s+(-d|--decode)[^\n;]*\|\s*(ba|z)?sh\b", "Ejecución de código codificado."),
    (r"(^|[\s;&|(`'\"])eval\s", "`eval` ejecuta código que no se puede revisar antes."),
    (r"(source|\.|bash|sh)\s+<\(", "Ejecutar el resultado de un proceso sin revisarlo."),
    (r"disableAllHooks", "Intento de desactivar los hooks."),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "Fork bomb."),
]

GLOBAL_ASK = [
    (r"while\s+(true|:)\b|for\s*\(\(\s*;\s*;\s*\)\)", "Bucle infinito: puede quedarse corriendo en el login node."),
]


def check_redirects(cmd: str, v: Verdict) -> None:
    for m in re.finditer(r"(?<![0-9<])&?>>?\|?\s*['\"]?([^\s;&|)'\"<>]+)", cmd):
        target = m.group(1)
        if target.startswith("&") or target in ("/dev/null", "/dev/stdout", "/dev/stderr"):
            continue
        t = _norm(target)
        if any(r in t for r in READONLY):
            v.d(f"Redirección que escribe en kaggle_data (`{target}`): el dataset es de solo lectura.")
        elif is_foreign(t):
            v.d(f"Redirección que escribe en archivos de otra persona (`{target}`).")
        elif SELF_PROTECTED.search(t):
            v.d("Escritura sobre la configuración del guardarraíl.")
        elif SECRETS.search(t):
            v.d(f"Escritura sobre credenciales o ~/.ssh (`{target}`).")
        elif SHELL_RC.search(t):
            v.a(f"Modificar `{target}` cambia el entorno de todas las sesiones de Owen.")
        elif is_project_toplevel(t) and _norm(t).rstrip("/") != PROJECT_ROOT:
            v.a(f"Crear o sobrescribir `{target}` en la raíz del proyecto compartido.")


# --------------------------------------------------------------------------- #
# Reglas por subcomando
# --------------------------------------------------------------------------- #
def check_ssh(tokens: list[str], v: Verdict) -> tuple[list[str], bool]:
    """Analiza `ssh ...`; devuelve (comando remoto, es_ssh)."""
    i = 1
    flags = []
    while i < len(tokens) and tokens[i].startswith("-"):
        t = tokens[i]
        flags.append(t)
        if len(t) == 2 and t[1] in SSH_OPTS_WITH_VALUE:
            i += 1
        i += 1
    host = tokens[i] if i < len(tokens) else ""
    rest = tokens[i + 1:]
    host_only = host.split("@")[-1]
    joined = " ".join(flags)
    if re.search(r"(^|\s)-[a-zA-Z]*[RD]", joined):
        v.d("Túnel SSH inverso o dinámico (-R/-D): expone el login node.")
    elif re.search(r"(^|\s)-[a-zA-Z]*L", joined):
        v.a("Túnel SSH local (-L).")
    if host and host_only not in ALLOWED_SSH_HOSTS:
        v.a(f"SSH a `{host}`: fuera del login node. Entrar a nodos de cómputo sin job asignado no está permitido.")
    if host and not rest:
        v.a("Sesión SSH interactiva: el agente se quedaría esperando.")
    return rest, True


def check_rm(args: list[str], v: Verdict) -> None:
    flags = " ".join(a for a in args if a.startswith("-"))
    targets = non_flags(args)
    if re.search(r"(^|\s)(-[a-zA-Z]*[rR]|--recursive)", flags):
        v.d("Borrado recursivo (rm -r). Mueve a `_to_delete/` y deja que Owen borre." + NO_EVADE)
        return
    if touches(targets, READONLY):
        v.d("Borrar dentro de kaggle_data: el dataset es de solo lectura." + NO_EVADE)
        return
    if any(is_foreign(t) for t in targets):
        v.d("Borrar archivos de otra persona." + NO_EVADE)
        return
    if any(SELF_PROTECTED.search(t) for t in targets):
        v.d("Borrar archivos del guardarraíl.")
        return
    dangerous = {"*", "/", "~", "$HOME", "${HOME}", ".", "..", "/*", "~/*", "./*"}
    if any(t in dangerous or _norm(t).rstrip("/") in (PROJECT_ROOT, f"/lustre/home/{USER}") for t in targets):
        v.d("rm sobre un comodín o directorio raíz." + NO_EVADE)
        return
    v.a("Borrar archivos (no hay papelera en Lustre): " + " ".join(targets[:5]))


def check_writes(verb: str, args: list[str], v: Verdict, remote: bool) -> None:
    targets = non_flags(args)
    if verb in COPY_VERBS:
        dest = targets[-1] if targets else ""
        sources = targets[:-1]
        if any(r in _norm(dest) for r in READONLY):
            v.d("Copiar hacia kaggle_data: el dataset es de solo lectura." + NO_EVADE)
        if is_foreign(dest):
            v.d("Copiar hacia directorios de otra persona.")
        if SELF_PROTECTED.search(dest):
            v.d("Sobrescribir archivos del guardarraíl.")
        if SECRETS.search(" ".join(targets)):
            v.d("Copiar credenciales o archivos de ~/.ssh.")
        remote_src = [s for s in sources if re.match(r"^[\w.@-]+:", s)]
        if remote_src and not re.match(r"^[\w.@-]+:", dest):
            if touches(remote_src, READONLY):
                v.d("Sacar datos de kaggle_data fuera del cluster (licencia de la competencia).")
            else:
                v.a("Copiar archivos del cluster a la máquina local: " + " ".join(remote_src[:3]))
        recursive = any(re.fullmatch(r"-[a-zA-Z]*[rRa][a-zA-Z]*|--recursive|--archive", a) for a in args)
        if recursive and touches(sources, READONLY):
            v.d("Recorrer/copiar kaggle_data completo desde el login node; hazlo en un job." + NO_EVADE)
        elif recursive and (remote or ON_CLUSTER) and touches(targets, (PROJECT_ROOT, "/lustre/")):
            v.a("Copia recursiva de datos en Lustre.")
        if verb == "rsync" and "--delete" in " ".join(args):
            v.d("rsync --delete borra en el destino.")
        return

    if touches(targets, READONLY) and verb != "rmdir":
        v.d(f"`{verb}` sobre kaggle_data: el dataset es de solo lectura." + NO_EVADE)
        return
    if any(is_foreign(t) for t in targets):
        v.d(f"`{verb}` sobre archivos de otra persona.")
        return
    if any(SELF_PROTECTED.search(t) for t in targets):
        v.d(f"`{verb}` sobre la configuración del guardarraíl.")
        return
    if verb in ("tee",) and any(SECRETS.search(t) for t in targets):
        v.d("Escribir en credenciales o ~/.ssh.")
        return
    if verb in ("tee",) and any(SHELL_RC.search(t) for t in targets):
        v.a("Modificar archivos de arranque del shell.")
    if verb == "dd":
        v.d("`dd` puede sobrescribir dispositivos o archivos completos.")
        return
    if verb == "shred":
        v.d("`shred` destruye archivos de forma irrecuperable.")
        return
    if verb == "chown":
        v.d("`chown` es tarea de administración.")
        return
    if verb == "setfacl":
        v.d("Cambiar ACLs es tarea de administración (pídeselo a ACARUS).")
        return
    if verb in ("chmod", "chgrp"):
        mode = " ".join(args)
        mode_arg = targets[0] if verb == "chmod" and targets else ""
        world_writable = bool(
            re.fullmatch(r"[0-7]?[0-7]{2}[2367]", mode_arg)
            or re.search(r"(^|,)[ugo]*[oa][ugo]*[+=][rwxXst]*w", mode_arg)
        )
        if world_writable:
            v.d("Dar permisos de escritura a todo el mundo.")
            return
        if any(_norm(t).rstrip("/") == PROJECT_ROOT for t in targets):
            v.d("Cambiar permisos de la raíz del proyecto compartido.")
            return
        if any(SECRETS.search(t) for t in targets):
            v.d("Cambiar permisos de ~/.ssh o credenciales.")
            return
        if re.search(r"(^|\s)(-[a-zA-Z]*R|--recursive)", mode):
            v.a(f"`{verb} -R` cambia permisos de muchos archivos a la vez.")
        elif remote or ON_CLUSTER:
            v.a(f"`{verb}` en el cluster.")
        return
    if verb == "mv":
        if remote or ON_CLUSTER:
            v.a("Mover archivos en el cluster: " + " ".join(targets[:4]))
        if any(SECRETS.search(t) for t in targets):
            v.d("Mover credenciales o ~/.ssh.")
        return
    if verb in ("mkdir", "touch", "ln") and any(
        is_project_toplevel(t) and _norm(t).rstrip("/") != PROJECT_ROOT for t in targets
    ):
        v.a("Crear algo directamente en la raíz del proyecto compartido.")


def check_traversal(verb: str, args: list[str], v: Verdict, under_job: bool) -> None:
    if under_job:
        return
    if verb in ("ls",) and re.search(r"(^|\s)-[a-zA-Z]*R", " ".join(args)) and touches(args, READONLY):
        v.d("`ls -R` sobre kaggle_data (~820k archivos) desde el login node; usa un job." + NO_EVADE)
    elif verb in TRAVERSE_VERBS and touches(args, READONLY):
        if verb in ("grep", "rg") and not re.search(r"(^|\s)-[a-zA-Z]*[rR]", " ".join(args)):
            return
        if verb in ("wc", "md5sum", "sha256sum") and not any("*" in a for a in args):
            return
        if verb in ("cp", "rsync"):
            return  # cubierto en check_writes
        v.d(f"`{verb}` recorriendo kaggle_data desde el login node: hazlo en un job de SLURM." + NO_EVADE)


def check_find(args: list[str], v: Verdict) -> None:
    joined = " ".join(args)
    if re.search(r"(^|\s)-delete\b", joined) or re.search(
        r"-(exec|execdir|ok|okdir)\s+(rm|mv|chmod|chgrp|chown|shred|truncate|unlink)\b", joined
    ):
        v.d("`find` con borrado o modificación masiva." + NO_EVADE)


def check_scancel(args: list[str], v: Verdict) -> None:
    bad = re.compile(r"^(-u|--user|-A|--account|-p|--partition|-t|--state|-n|--name|--jobname|-w|--nodelist|"
                     r"--me|-q|--qos|-R|--reservation|-M|--clusters|-b|--batch|-f|--full)(=.*)?$")
    if any(bad.match(a) for a in args):
        v.d("`scancel` con filtros cancela jobs en masa (posiblemente de otros)." + NO_EVADE)
        return
    ids = [a for a in args if re.fullmatch(r"\d+(_\d+|_\[[\d,-]+\])?(\.\w+)?", a)]
    if not ids:
        v.d("`scancel` sin un ID de job concreto.")
        return
    v.a("Cancelar job(s) " + ", ".join(ids) + ". Confirma que son tuyos y de esta tarea.")


def check_slurm_admin(verb: str, args: list[str], v: Verdict) -> None:
    sub = args[0] if args else ""
    if verb == "scontrol":
        if sub in ("update", "delete", "create", "reconfigure", "shutdown", "takeover", "setdebug",
                   "setdebugflags", "reboot", "power", "write"):
            v.d(f"`scontrol {sub}` es tarea de administración.")
        elif sub in ("hold", "release", "requeue", "requeuehold", "suspend", "resume", "top", "uhold"):
            v.a(f"`scontrol {sub}` modifica un job.")
    elif verb == "sacctmgr":
        if any(a in ("add", "create", "modify", "update", "delete", "remove", "archive", "load") for a in args):
            v.d("`sacctmgr` con cambios es tarea de administración.")
    elif verb in ("srun", "salloc"):
        v.a(f"`{verb}` abre una asignación interactiva o ejecuta en nodos de cómputo.")


def check_lfs(args: list[str], v: Verdict) -> None:
    sub = args[0] if args else ""
    if sub in ("setstripe", "migrate", "mirror", "swap_layouts", "setdirstripe", "mkdir", "rm_entry",
               "hsm_set", "hsm_clear", "hsm_archive", "hsm_release", "hsm_remove", "ladvise", "setquota"):
        v.d(f"`lfs {sub}` cambia la configuración de Lustre.")
    elif sub == "project" and any(a in ("-p", "-s", "-C", "-r", "-k") for a in args[1:]):
        v.d("`lfs project` con cambios (cuotas de proyecto) es tarea de administración.")


def check_git(args: list[str], v: Verdict) -> None:
    # Saltar opciones globales de git que llevan valor: -C <dir>, -c <k=v>, --git-dir <dir>...
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 2 if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else 1
    args = args[i:]
    sub = args[0] if args else ""
    joined = " ".join(args)
    if sub == "push" and (re.search(r"(^|\s)(-f|--force|--force-with-lease|--mirror|--delete|-d)\b", joined)
                          or re.search(r"\s\+\S+", joined)):
        v.d("`git push` forzado o que borra ramas reescribe la historia compartida.")
    elif sub == "reset" and "--hard" in joined:
        v.d("`git reset --hard` descarta cambios sin recuperación.")
    elif sub == "clean" and re.search(r"(^|\s)-[a-zA-Z]*f", joined):
        v.d("`git clean -f` borra archivos no versionados.")
    elif sub in ("filter-branch", "filter-repo"):
        v.d("Reescribir la historia del repo.")
    elif sub == "rebase" or (sub == "branch" and re.search(r"(^|\s)-D\b", joined)):
        v.a(f"`git {sub}` modifica la historia o borra ramas.")
    elif sub in ("checkout", "restore") and re.search(r"(\s--\s|\s\.\s*$|--worktree)", joined + " "):
        v.a("Descartar cambios locales.")
    elif sub == "config" and "--global" in joined:
        v.a("Cambiar la configuración global de git.")
    elif sub == "stash" and re.search(r"\b(drop|clear)\b", joined):
        v.a("Borrar stashes.")


def check_python(verb: str, args: list[str], v: Verdict, remote: bool, under_job: bool) -> None:
    joined = " ".join(args)
    if SKILL_SCRIPTS.search(joined):
        return  # scripts de esta skill (linter, pruebas del hook)
    if args[:2] == ["-m", "pip"] or args[:2] == ["-m", "pip3"]:
        check_pip(args[2:], v)
        return
    if re.search(r"-m\s+(http\.server|jupyter|notebook|tensorboard|mlflow|streamlit|gradio)", joined):
        v.a("Levantar un servidor en el login node.")
        return
    if under_job:
        return
    on_login = remote or ON_CLUSTER
    if verb in ("torchrun", "accelerate", "deepspeed"):
        v.d(f"`{verb}` es entrenamiento: va en un job de SLURM, no en el login node." + NO_EVADE)
        return
    script = next((a for a in args if not a.startswith("-")), "")
    if on_login and HEAVY_PY.search(script):
        v.d(f"`{script}` parece cómputo pesado: envíalo con sbatch, no en el login node." + NO_EVADE)
    elif on_login:
        v.a("Ejecutar Python en el login node compartido. Confirma que es algo ligero (< 1 min, poca RAM).")
    else:
        v.a("Ejecutar Python en la laptop. En modo remoto el código del proyecto debe correr en Yuca.")


def check_pip(args: list[str], v: Verdict) -> None:
    joined = " ".join(args)
    if "--break-system-packages" in joined:
        v.d("pip --break-system-packages.")
    elif "--user" in joined:
        v.a("pip --user instala fuera del entorno del proyecto.")
    elif args and args[0] == "uninstall":
        v.a("Desinstalar paquetes.")


def check_conda(args: list[str], v: Verdict) -> None:
    sub = args[0] if args else ""
    joined = " ".join(args)
    if sub in ("install", "update", "upgrade", "remove", "uninstall", "create", "clean", "config") or (
        sub == "env" and re.search(r"\b(remove|update|create)\b", joined)
    ):
        target = "base" if not re.search(r"(-n|--name|-p|--prefix)\s+\S+", joined) or re.search(r"-n\s+base\b", joined) else "otro"
        v.a(f"`conda {sub}` modifica entornos" + (" (posiblemente base)" if target == "base" else "") + ".")


def check_sbatch(args: list[str], v: Verdict, cwd: str) -> None:
    joined = " ".join(args)
    if "--test-only" in joined:
        return
    if "--wrap" in joined:
        v.a("`sbatch --wrap`: el comando no queda en un script versionado.")
        return
    # Separar opciones de la ruta del script.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import check_slurm  # type: ignore
    except Exception:  # pragma: no cover
        v.a("Envío de job (no pude cargar el linter para revisarlo).")
        return
    opt_tokens, script = [], ""
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("-"):
            opt_tokens.append(a)
            if len(a) == 2 and a[1] in check_slurm._SHORT_WITH_VALUE and i + 1 < len(args):
                opt_tokens.append(args[i + 1])
                i += 1
            elif a.startswith("--") and "=" not in a and i + 1 < len(args) and not args[i + 1].startswith("-") \
                    and a[2:] not in ("exclusive", "parsable", "requeue", "no-requeue", "wait", "test-only"):
                opt_tokens.append(args[i + 1])
                i += 1
        else:
            script = a
            break
        i += 1
    cli = check_slurm.parse_option_tokens(opt_tokens)
    if cli.get("account") and cli["account"] != ACCOUNT:
        v.d(f"El job usa la cuenta `{cli['account']}`; este proyecto es `{ACCOUNT}`.")
        return
    path = resolve_local(script, cwd)
    if not path:
        v.a(f"Envío de job `{script or '?'}`. No encontré el script localmente para revisarlo: "
            "verifica cuenta, tiempo, memoria y GPUs antes de aprobar.")
        return
    res = check_slurm.lint(path.read_text(encoding="utf-8", errors="replace"), ACCOUNT, cli)
    if res.errors:
        v.d("El script no pasa el linter:\n- " + "\n- ".join(res.errors))
        return
    msg = f"Enviar job {script}: {res.summary}."
    if res.warnings:
        msg += "\nAvisos:\n- " + "\n- ".join(res.warnings)
    msg += "\n(Se revisó la copia local; confirma que ya hiciste git push.)"
    v.a(msg)


def resolve_local(script: str, cwd: str) -> Path | None:
    if not script:
        return None
    s = _norm(script)
    candidates = []
    if s.startswith(REPO_REMOTE + "/"):
        s = s[len(REPO_REMOTE) + 1:]
    p = Path(s)
    if p.is_absolute():
        candidates.append(p)
    else:
        base = Path(cwd or os.getcwd())
        for parent in [base, *base.parents][:5]:
            candidates.append(parent / s)
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def check_secrets_read(verb: str, args: list[str], v: Verdict) -> None:
    if verb in ("cat", "less", "more", "head", "tail", "strings", "xxd", "od", "base64", "grep", "rg", "awk",
                "sed", "nano", "vim", "vi", "code", "type", "Get-Content", "gc", "bat", "python", "python3"):
        hits = [a for a in args if SECRETS.search(a) and not a.endswith(".pub")]
        if hits:
            v.d("Leer credenciales o llaves (" + ", ".join(hits[:3]) + "). Nunca deben pasar por el contexto del modelo.")
    if verb in ("printenv", "env", "set", "export") and not args:
        v.a("Volcar todas las variables de entorno puede exponer tokens.")


def analyze_tokens(tokens: list[str], v: Verdict, remote: bool, under_job: bool, cwd: str, depth: int = 0) -> bool:
    """Analiza un subcomando. Devuelve True si a partir de aquí todo es remoto (ssh)."""
    tokens = strip_wrappers(tokens)
    if not tokens or depth > 4:
        return remote
    verb = tokens[0].split("/")[-1].split("\\")[-1]
    args = tokens[1:]

    if verb == "ssh":
        rest, _ = check_ssh(tokens, v)
        if rest:
            analyze_tokens(rest, v, True, under_job, cwd, depth + 1)
        return True

    if verb in ("bash", "sh", "zsh", "dash") and "-c" in args:
        inner = " ".join(args[args.index("-c") + 1:])
        for seg in split_segments(inner):
            analyze_tokens(tokenize(seg), v, remote, under_job, cwd, depth + 1)
        return remote

    if verb in ("sudo", "su", "doas", "pkexec", "runuser"):
        v.d(f"`{verb}`: no se ejecutan comandos con privilegios elevados." + NO_EVADE)
    elif verb == "rm":
        check_rm(args, v)
    elif verb in WRITE_VERBS or verb in COPY_VERBS:
        check_writes(verb, args, v, remote)
    elif verb == "sed" and re.search(r"(^|\s)-[a-zA-Z]*i", " ".join(args)):
        targets = non_flags(args)[1:]
        if touches(targets, READONLY) or any(is_foreign(t) for t in targets):
            v.d("`sed -i` sobre archivos de solo lectura o de otra persona.")
        elif any(SELF_PROTECTED.search(t) for t in targets):
            v.d("`sed -i` sobre la configuración del guardarraíl.")
        elif any(SECRETS.search(t) for t in targets):
            v.d("`sed -i` sobre credenciales o ~/.ssh.")
        elif any(SHELL_RC.search(t) for t in targets):
            v.a("Modificar archivos de arranque del shell.")
        elif remote or ON_CLUSTER:
            v.a("`sed -i` edita archivos en el cluster sin pasar por git.")
    elif verb == "find":
        check_find(args, v)
    elif verb == "xargs" and re.search(r"\b(rm|mv|chmod|chgrp|chown|shred|kill)\b", " ".join(args)):
        v.d("`xargs` con borrado o modificación masiva." + NO_EVADE)
    elif verb == "scancel":
        check_scancel(args, v)
    elif verb in ("scontrol", "sacctmgr", "srun", "salloc"):
        check_slurm_admin(verb, args, v)
    elif verb == "sbatch":
        check_sbatch(args, v, cwd)
    elif verb == "lfs":
        check_lfs(args, v)
    elif verb == "git":
        check_git(args, v)
    elif re.fullmatch(r"python[0-9.]*|torchrun|accelerate|deepspeed|ipython", verb):
        check_python(verb, args, v, remote, under_job)
    elif verb in ("pip", "pip3", "uv"):
        check_pip(args[1:] if verb == "uv" else args, v)
    elif verb in ("conda", "mamba", "micromamba"):
        check_conda(args, v)
    elif verb in ("kill", "pkill", "killall"):
        if verb == "killall" or "-u" in args or "-1" in args:
            v.d(f"`{verb}` masivo.")
        else:
            v.a(f"`{verb}`: terminar procesos.")
    elif verb in ("nohup", "setsid", "disown", "daemonize"):
        v.d(f"`{verb}` deja procesos vivos en el login node; usa un job de SLURM.")
    elif verb == "crontab" and "-l" not in args:
        v.d("`crontab` programa tareas persistentes en el login node.")
    elif verb == "at" or (verb == "systemctl" and "--user" in args) or verb == "loginctl":
        v.d(f"`{verb}` deja tareas persistentes en el login node.")
    elif verb in ("mkfs", "fdisk", "parted", "wipefs", "chattr", "mount", "umount", "insmod", "rmmod", "modprobe"):
        v.d(f"`{verb}` es administración del sistema.")
    elif verb in ("jupyter", "tensorboard", "mlflow", "streamlit", "gradio", "nc", "ncat", "socat", "ngrok"):
        v.a(f"`{verb}` puede abrir un puerto o servidor en el login node.")
    elif verb in ("tmux", "screen") and not (args and args[0] in ("ls", "list-sessions", "-ls")):
        v.a(f"`{verb}` crea sesiones persistentes en el login node.")
    elif verb == "watch":
        m = re.search(r"(-n|--interval)[= ]?(\d+)", " ".join(args))
        if not m or int(m.group(2)) < 30:
            v.d("`watch` con intervalo < 30 s satura el controlador de SLURM; consulta como mucho cada 60 s.")
    elif verb in ("wget",) or (verb == "curl" and re.search(r"(^|\s)(-[a-zA-Z]*[oO]|--output|--remote-name)", " ".join(args))):
        v.a(f"Descarga de red con `{verb}`; confirma el tamaño y el destino.")
    elif verb in ("huggingface-cli", "hf") and "download" in args or verb == "kaggle" and "download" in " ".join(args):
        v.a("Descarga de modelos/datos; confirma tamaño, destino y cuota disponible.")

    check_traversal(verb, args, v, under_job)
    check_secrets_read(verb, args, v)
    return remote


def analyze_bash(cmd: str, cwd: str) -> Verdict:
    v = Verdict()
    for pattern, msg in GLOBAL_DENY:
        if re.search(pattern, cmd):
            v.d(msg + NO_EVADE)
    for pattern, msg in GLOBAL_ASK:
        if re.search(pattern, cmd):
            v.a(msg)
    check_redirects(cmd, v)
    # `cd kaggle_data && rm x`: el destino de la escritura es relativo y no se ve en los argumentos.
    for m in re.finditer(r"(?:^|[\s;&|('\"])(?:cd|pushd)\s+['\"]?(\S+)", cmd):
        dest = _norm(m.group(1))
        after = cmd[m.end():]
        writes = re.search(
            r"(^|[\s;&|('\"])(rm|mv|cp|rsync|chmod|chgrp|chown|setfacl|touch|mkdir|ln|tee|truncate|unlink|sed\s+-i)\s"
            r"|>>?\s*\S", after)
        if writes and any(r in dest for r in READONLY):
            v.d("Escritura después de `cd` a kaggle_data (solo lectura)." + NO_EVADE)
        elif writes and is_foreign(dest):
            v.d("Escritura después de `cd` a directorios de otra persona." + NO_EVADE)
    remote = False
    for seg in split_segments(cmd):
        remote = analyze_tokens(tokenize(seg), v, remote, False, cwd) or remote
    return v


def analyze_file_tool(tool: str, tool_input: dict) -> Verdict:
    v = Verdict()
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or tool_input.get("path") or "")
    p = _norm(path)
    if tool == "Read":
        if SECRETS.search(p) and not p.endswith(".pub"):
            v.d("Leer credenciales o llaves privadas.")
        return v
    if SELF_PROTECTED.search(p):
        v.d("Editar la configuración del guardarraíl o de esta skill. Si hace falta, que Owen lo haga a mano.")
    elif SECRETS.search(p):
        v.d("Escribir en credenciales o ~/.ssh.")
    elif any(r in p for r in READONLY):
        v.d("Escribir dentro de kaggle_data (solo lectura).")
    elif is_foreign(p):
        v.d("Escribir en archivos de otra persona.")
    elif SHELL_RC.search(p):
        v.a("Modificar archivos de arranque del shell.")
    elif re.search(r"(^|/)CLAUDE\.md$", p):
        v.a("Cambiar CLAUDE.md modifica las instrucciones de futuras sesiones del agente.")
    return v


def log(event: dict, decision: str, reasons: list[str]) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": _dt.datetime.now().isoformat(timespec="seconds"),
                "decision": decision,
                "tool": event.get("tool_name"),
                "input": event.get("tool_input"),
                "reasons": reasons,
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def emit(decision: str, reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def decide(event: dict) -> tuple[str | None, list[str]]:
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    if tool in ("Bash", "PowerShell"):
        v = analyze_bash(str(tool_input.get("command", "")), cwd)
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Read"):
        v = analyze_file_tool(tool, tool_input)
    else:
        return None, []
    if v.deny:
        return "deny", v.deny
    if v.ask:
        return "ask", v.ask
    return None, []


def main() -> int:
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
        decision, reasons = decide(event)
    except Exception as exc:  # falla cerrado
        emit("deny", f"Guardarraíl de Yuca: error interno ({type(exc).__name__}: {exc}). Bloqueado por precaución.")
        return 0
    if decision:
        prefix = "Guardarraíl de Yuca — " + ("BLOQUEADO" if decision == "deny" else "requiere confirmación") + ":\n- "
        emit(decision, prefix + "\n- ".join(reasons))
        log(event, decision, reasons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
