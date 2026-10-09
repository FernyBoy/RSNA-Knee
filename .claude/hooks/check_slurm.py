#!/usr/bin/env python3
"""Linter de scripts SLURM para el cluster Yuca (proyecto p082).

Uso:
    python check_slurm.py jobs/train.slurm [--account p082]

Salida: lista de errores (bloquean el envío) y advertencias (requieren
confirmación humana), más un resumen de recursos.
Códigos de salida: 0 = OK, 1 = solo advertencias, 2 = errores.

Solo lee el texto del script; no se conecta a nada. Se puede ejecutar en la
laptop o en el cluster. guard_hook.py lo importa para revisar cada `sbatch`.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field

DEFAULT_ACCOUNT = "p082"
READONLY_MARKERS = ("kaggle_data",)

# Umbrales: por encima de esto se pide confirmación humana (nivel 2).
WARN_GPUS = 1
WARN_NODES = 1
WARN_HOURS = 24
WARN_MEM_GB = 256
WARN_CPUS = 64
WARN_ARRAY = 50

# Opciones cortas de sbatch que llevan valor.
_SHORT_WITH_VALUE = set("AJtopeNncGwxDdLMqbiSrkuWFmQIlT")


@dataclass
class LintResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    opts: dict[str, str] = field(default_factory=dict)
    summary: str = ""

    @property
    def code(self) -> int:
        if self.errors:
            return 2
        if self.warnings:
            return 1
        return 0


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
_LONG_ALIASES = {
    "A": "account", "J": "job-name", "t": "time", "o": "output", "e": "error",
    "p": "partition", "N": "nodes", "n": "ntasks", "c": "cpus-per-task",
    "G": "gpus", "w": "nodelist", "x": "exclude", "a": "array",
}


def parse_option_tokens(tokens: list[str]) -> dict[str, str]:
    """Convierte ['-A', 'p082', '--time=1:00:00', '--exclusive'] en un dict."""
    opts: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--"):
            body = tok[2:]
            if "=" in body:
                k, v = body.split("=", 1)
            else:
                k = body
                # Algunas opciones largas toman valor separado por espacio.
                if i + 1 < len(tokens) and not tokens[i + 1].startswith("-") and k not in (
                    "exclusive", "test-only", "parsable", "requeue", "no-requeue", "wait",
                ):
                    v = tokens[i + 1]
                    i += 1
                else:
                    v = ""
            opts[k] = v
        elif tok.startswith("-") and len(tok) >= 2:
            letter = tok[1]
            key = _LONG_ALIASES.get(letter, letter)
            if len(tok) > 2:
                opts[key] = tok[2:].lstrip("=")
            elif letter in _SHORT_WITH_VALUE and i + 1 < len(tokens):
                opts[key] = tokens[i + 1]
                i += 1
            else:
                opts[key] = ""
        i += 1
    return opts


def parse_sbatch_header(text: str) -> tuple[dict[str, str], str, list[str]]:
    """Devuelve (opciones #SBATCH, cuerpo, problemas de formato).

    SLURM deja de leer directivas #SBATCH en la primera línea que no sea
    comentario ni vacía; las que vengan después se ignoran en silencio.
    """
    problems: list[str] = []
    lines = text.splitlines()
    tokens: list[str] = []
    body_start = len(lines)
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if idx == 0 and line.startswith("#!"):
            continue
        if not line or (line.startswith("#") and not line.startswith("#SBATCH")):
            continue
        if line.startswith("#SBATCH"):
            directive = line[len("#SBATCH"):].split("#", 1)[0].strip()
            tokens.extend(directive.split())
            continue
        body_start = idx
        break
    for raw in lines[body_start:]:
        if raw.strip().startswith("#SBATCH"):
            problems.append(
                "Hay directivas #SBATCH después del primer comando; SLURM las ignora. "
                "Muévelas al bloque inicial."
            )
            break
    body = "\n".join(lines[body_start:])
    return parse_option_tokens(tokens), body, problems


def parse_time_hours(value: str) -> float | None:
    """Formatos de SLURM: M, M:S, H:M:S, D-H, D-H:M, D-H:M:S."""
    value = value.strip()
    if not value or value.lower() in ("infinite", "unlimited"):
        return None
    days = 0
    if "-" in value:
        d, value = value.split("-", 1)
        days = int(d)
        parts = [int(p) for p in value.split(":")]
        while len(parts) < 3:
            parts.append(0)
        h, m, s = parts[:3]
    else:
        parts = [int(p) for p in value.split(":")]
        if len(parts) == 1:
            h, m, s = 0, parts[0], 0
        elif len(parts) == 2:
            h, m, s = 0, parts[0], parts[1]
        else:
            h, m, s = parts[:3]
    return days * 24 + h + m / 60 + s / 3600


def parse_mem_gb(value: str) -> float | None:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KMGTkmgt]?)[Bb]?", value.strip())
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or "M").upper()
    return num * {"K": 1 / 1024 / 1024, "M": 1 / 1024, "G": 1, "T": 1024}[unit]


def gpu_count(opts: dict[str, str]) -> int:
    nodes = _int(opts.get("nodes", "1").split("-")[-1], 1)
    for key in ("gres",):
        v = opts.get(key, "")
        m = re.search(r"gpu(?::[\w-]+)?:(\d+)", v)
        if m:
            return int(m.group(1)) * nodes
        if re.search(r"\bgpu\b", v):
            return 1 * nodes
    for key in ("gpus", "gpus-per-task"):
        if opts.get(key):
            m = re.search(r"(\d+)\s*$", opts[key])
            if m:
                return int(m.group(1))
    if opts.get("gpus-per-node"):
        m = re.search(r"(\d+)\s*$", opts["gpus-per-node"])
        if m:
            return int(m.group(1)) * nodes
    return 0


def _int(v: str, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# Reglas sobre el cuerpo del script
# --------------------------------------------------------------------------- #
_BODY_ERRORS = [
    (r"(^|[\s;&|(])sudo\s", "El script usa sudo."),
    (r"(^|[\s;&|(])rm\s+(-\S*[rR]|--recursive)", "El script usa rm recursivo. Escribe en un runs/$SLURM_JOB_ID nuevo en vez de borrar."),
    (r"(^|[\s;&|(])scancel\s", "El script cancela jobs (scancel)."),
    (r"(^|[\s;&|(])(chmod|chgrp)\s+(-\S*R|--recursive)", "El script cambia permisos de forma recursiva."),
    (r"(^|[\s;&|(])(setfacl|chown)\s", "El script cambia ACLs o dueños."),
    (r"curl\s[^\n]*(\s-k\b|--insecure)|--no-check-certificate|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0|"
     r"PYTHONHTTPSVERIFY\s*=\s*['\"]?0|verify\s*=\s*False|--trusted-host|GIT_SSL_NO_VERIFY|sslVerify\s*=?\s*false",
     "El script desactiva la verificación TLS. Con el Fortinet de UniSon hay que conseguir la CA, no saltarse la verificación."),
    (r"(curl|wget)\s[^\n|]*\|\s*(ba|z)?sh\b", "El script descarga y ejecuta código sin revisarlo (curl | sh)."),
]

_READONLY_WRITE = re.compile(
    r"(^|[\s;&|(])(rm|mv|chmod|chgrp|chown|setfacl|truncate|touch|mkdir|ln|tee|unlink)\s[^\n;&|]*kaggle_data"
    r"|>>?\s*['\"]?\S*kaggle_data"
    r"|(^|[\s;&|(])(cp|rsync)\s[^\n;&|]*\s\S*kaggle_data\S*\s*($|[;&|])"
    r"|--(out|output|save|dest|out_dir|output_dir|save_dir)[= ]\S*kaggle_data"
)


def lint(text: str, account: str = DEFAULT_ACCOUNT, cli_opts: dict[str, str] | None = None) -> LintResult:
    res = LintResult()
    if not text.lstrip().startswith("#!"):
        res.errors.append("Falta el shebang (#!/bin/bash) en la primera línea.")

    opts, body, problems = parse_sbatch_header(text)
    res.warnings.extend(problems)
    if cli_opts:
        opts.update(cli_opts)  # la línea de comandos sobrescribe al script
    res.opts = opts

    # Cuenta
    acct = opts.get("account")
    if not acct:
        res.errors.append(f"Falta la cuenta: agrega `#SBATCH -A {account}`.")
    elif acct != account:
        res.errors.append(f"La cuenta es `{acct}`, pero este proyecto usa `{account}`.")

    # Tiempo
    hours = None
    if not opts.get("time"):
        res.errors.append("Falta `--time`. Sin límite el job puede quedarse con recursos días enteros.")
    else:
        try:
            hours = parse_time_hours(opts["time"])
        except ValueError:
            res.errors.append(f"No entiendo el formato de --time `{opts['time']}`.")
        if hours is None and opts.get("time", "").lower() in ("infinite", "unlimited"):
            res.errors.append("--time ilimitado no está permitido.")
        elif hours is not None and hours > WARN_HOURS:
            res.warnings.append(f"Tiempo solicitado {hours:.1f} h (> {WARN_HOURS} h).")

    # Memoria
    mem_gb = None
    if not any(opts.get(k) for k in ("mem", "mem-per-cpu", "mem-per-gpu")):
        res.errors.append("Falta la memoria (`--mem` o `--mem-per-cpu`).")
    elif opts.get("mem"):
        mem_gb = parse_mem_gb(opts["mem"])
        if opts["mem"].strip() == "0":
            res.warnings.append("`--mem=0` pide TODA la memoria del nodo.")
        elif mem_gb and mem_gb > WARN_MEM_GB:
            res.warnings.append(f"Memoria {mem_gb:.0f} GB (> {WARN_MEM_GB} GB).")

    # Nombre y logs
    if not opts.get("job-name"):
        res.warnings.append("Falta `-J` (nombre del job); ayuda a identificarlo en squeue.")
    out = opts.get("output", "")
    if not out:
        res.errors.append("Falta `-o logs/%x_%j.out`; sin eso el log cae en el directorio de envío.")
    else:
        if "%j" not in out and "%A" not in out:
            res.errors.append(f"El log `{out}` no incluye %j: cada envío sobrescribiría el anterior.")
        if not re.search(r"(^|/)logs/", out):
            res.warnings.append(f"El log `{out}` no está en logs/.")
        if any(m in out for m in READONLY_MARKERS):
            res.errors.append("El log apunta a kaggle_data (solo lectura).")

    # Recursos
    gpus = gpu_count(opts)
    nodes = _int(opts.get("nodes", "1").split("-")[-1], 1)
    cpus = _int(opts.get("cpus-per-task", "1"), 1)
    part = opts.get("partition", "")
    if gpus > WARN_GPUS:
        res.warnings.append(f"Pide {gpus} GPUs (> {WARN_GPUS}).")
    if nodes > WARN_NODES:
        res.warnings.append(f"Pide {nodes} nodos (> {WARN_NODES}).")
    if cpus > WARN_CPUS:
        res.warnings.append(f"Pide {cpus} CPUs por tarea (> {WARN_CPUS}).")
    if "exclusive" in opts:
        res.warnings.append("`--exclusive` reserva el nodo entero aunque no lo uses.")
    if not part:
        res.warnings.append("No declara partición; confirma con `sinfo -s` cuál corresponde.")
    elif gpus and part == "cpu":
        res.errors.append("Pide GPU pero la partición es `cpu`.")
    if opts.get("array"):
        arr = opts["array"]
        m = re.search(r"(\d+)-(\d+)", arr)
        size = (int(m.group(2)) - int(m.group(1)) + 1) if m else len(arr.split(","))
        if size > WARN_ARRAY:
            res.warnings.append(f"Array de {size} tareas (> {WARN_ARRAY}).")
        if "%" not in arr:
            res.warnings.append("El array no limita concurrencia (agrega `%N`, p. ej. `0-99%4`).")

    # Cuerpo (sin comentarios, para no marcar código desactivado)
    body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
    if not re.search(r"^\s*set\s+-[a-z]*e", body, re.M):
        res.warnings.append("Falta `set -euo pipefail`: si un paso falla, el script sigue como si nada.")
    for pattern, msg in _BODY_ERRORS:
        if re.search(pattern, body, re.M):
            res.errors.append(msg)
    if _READONLY_WRITE.search(body):
        res.errors.append("El script parece escribir dentro de kaggle_data (solo lectura).")
    if re.search(r"rm\s+(-\S+\s+)*\$\{?\w+\}?/", body) and not re.search(r"\$\{\w+:\?", body):
        res.warnings.append("Hay `rm` sobre `$VAR/...`; usa `${VAR:?}` para que falle si la variable está vacía.")

    res.summary = (
        f"cuenta={acct or '?'} partición={part or '?'} nodos={nodes} gpus={gpus} "
        f"cpus/tarea={cpus} mem={opts.get('mem') or opts.get('mem-per-cpu') or opts.get('mem-per-gpu') or '?'} "
        f"tiempo={opts.get('time', '?')} log={out or '?'}"
    )
    return res


def format_result(path: str, res: LintResult) -> str:
    lines = [f"{path}: {res.summary}"]
    for e in res.errors:
        lines.append(f"  ERROR: {e}")
    for w in res.warnings:
        lines.append(f"  AVISO: {w}")
    if res.code == 0:
        lines.append("  OK")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scripts", nargs="+")
    ap.add_argument("--account", default=DEFAULT_ACCOUNT)
    args = ap.parse_args(argv)
    worst = 0
    for path in args.scripts:
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"{path}: no se pudo leer ({exc})")
            worst = 2
            continue
        res = lint(text, args.account)
        print(format_result(path, res))
        worst = max(worst, res.code)
    return worst


if __name__ == "__main__":
    sys.exit(main())
