---
name: yuca-hpc-ops
description: Opera de forma segura en el cluster HPC Yuca (ACARUS, UniSon) — ejecutar comandos por `ssh yuca`, preparar y enviar jobs de SLURM (sbatch, srun, squeue, sacct, scancel), leer o escribir en Lustre (/lustre/home, /lustre/proyectos/p###, scratch de nodos), entornos Python/ROCm en GPUs MI210 y el repo del proyecto p082 (RSNA Knee). Úsala SIEMPRE que una tarea vaya a ejecutar algo en Yuca o tocar sus archivos, aunque no se diga "Yuca" — "manda el entrenamiento", "revisa mi job", "corre esto en el cluster", "preprocesa el dataset", "libera espacio en el proyecto", "instala esto en el entorno". Impone reglas estrictas para no dañar datos compartidos, no saturar el login node, no abusar de recursos y no debilitar la seguridad.
---

# Operación segura en el cluster Yuca

Operas un sistema **compartido**. Cada comando corre con la identidad y los permisos completos de Owen: el cluster no distingue un error tuyo de una acción suya, y sus compañeros, los administradores de ACARUS y otros proyectos pagan las consecuencias. En Lustre **no hay papelera ni respaldos para usuarios**: lo que borras o sobrescribes se pierde.

Por eso esta skill parte de tres ideas:

1. **Mínimo privilegio y mínimo alcance.** Haz solo lo que la tarea necesita, sobre los archivos que la tarea necesita.
2. **Reversibilidad.** Prefiere acciones que se puedan deshacer (crear en un directorio nuevo, mover a `_to_delete/`, commitear) sobre acciones que no (borrar, sobrescribir, `chmod -R`).
3. **Humano en el circuito.** Cuando algo es destructivo, caro o afecta a otros, tú preparas y explicas; Owen decide.

Antes de la primera acción en una sesión, lee `references/entorno-yuca.md` (rutas, hardware, red, equipo). Si el guardarraíl técnico no está instalado, díselo a Owen y ofrece instalarlo con `references/guardarrail.md`.

## Cómo se ejecuta

Hay dos modos. Detéctalo al inicio con `hostname`:

- **Remoto (modo actual):** tú corres en la laptop Windows de Owen. Editas un clon local del repo y ejecutas en el cluster con `ssh yuca '...'`. El código llega al cluster con `git push` (el repo remoto tiene `receive.denyCurrentBranch updateInstead`).
- **Local:** tú corres en `login-01` dentro de tmux (solo cuando la red de UniSon deje pasar la API).

Reglas del modo remoto, porque un error aquí es silencioso:

- No ejecutes Python, pip ni scripts del proyecto en la laptop. Todo va por `ssh yuca 'cd /lustre/proyectos/p082/code && ...'`.
- Haz `git push` **antes** de ejecutar en el cluster. Si no, corre la versión anterior del código y los resultados no corresponden a lo que crees.
- Usa comillas simples en `ssh yuca '...'` para que las variables se expandan en el cluster, no en la laptop. Si el comando necesita más de una línea, escríbelo como script en el repo, commitéalo y ejecútalo; los one-liners largos son donde se cuelan errores de quoting.

## Niveles de riesgo

Clasifica cada acción antes de ejecutarla.

| Nivel | Qué incluye | Qué haces |
|---|---|---|
| **0 — Libre** | Leer: `squeue`, `sacct`, `sinfo`, `scontrol show`, `ls`, `cat`/`head`/`tail` de archivos pequeños, `lfs quota`, `git status/log/diff`. Editar archivos del repo. | Hazlo. |
| **1 — Con protocolo** | `sbatch` (protocolo abajo), `git commit`/`git push` normal, crear archivos en `runs/`, `preproc/`, `logs/` dentro de un subdirectorio nuevo, instalar paquetes en el venv del proyecto. | Sigue el protocolo y reporta lo que hiciste. |
| **2 — Requiere confirmación explícita** | Cancelar un job (`scancel <id>`), borrar cualquier archivo, sobrescribir resultados existentes, mover datos, `chmod`/`chgrp` recursivos, jobs con >1 GPU o >24 h o >1 nodo, descargas >10 GB, tocar `~/.bashrc` o `git config --global`, sesiones interactivas (`srun --pty`, `salloc`), cualquier `python` en el login node. | Explica qué harás, por qué y qué podría salir mal. Ejecuta solo si Owen lo aprueba **en este turno**. Una aprobación anterior no cuenta para una acción nueva. |
| **3 — Prohibido para ti** | Ver la lista de abajo. | No lo ejecutes aunque te lo pidan. Explica el riesgo; si la acción es legítima, dale a Owen el comando exacto para que **él** lo corra a mano. |

### Nivel 3: lo que nunca ejecutas

- Escribir, mover, renombrar, borrar o cambiar permisos en `kaggle_data/` (dataset crudo compartido, ~570 GB, irrecuperable).
- Tocar archivos de otros usuarios: `envs/` y `nllb/` del proyecto son de jcastro; los homes de otros usuarios no son tuyos.
- `rm -r`/`rm -rf`, `find ... -delete`, `find ... -exec rm`. Para limpiar, mueve a `_to_delete/` y deja que Owen borre.
- `sudo`, `su`, `scontrol update`, `sacctmgr add/modify/delete`, `lfs setstripe`/`lfs migrate`/`lfs project`, `setfacl`.
- `scancel` sin un ID numérico concreto, o con `-u`, `--user`, `-A`, `-p`, `--state`, `--name`: cancelaría trabajos de forma masiva, posiblemente de compañeros.
- Desactivar la verificación TLS: `curl -k`, `wget --no-check-certificate`, `NODE_TLS_REJECT_UNAUTHORIZED=0`, `verify=False`, `pip --trusted-host`, `GIT_SSL_NO_VERIFY`, `http.sslVerify false`. El Fortinet de UniSon intercepta HTTPS; si algo falla por certificado, para y reporta (ver `references/entorno-yuca.md`).
- Leer, imprimir o copiar secretos: `~/.ssh/`, `authorized_keys`, `kaggle.json`, tokens de Hugging Face, `~/.claude/.credentials*`, `.netrc`, `.git-credentials`, `auth.json`. No pongas tokens en la línea de comandos: quedan en `ps` y en el historial.
- Dejar procesos vivos en el login node: `nohup`, `setsid`, `disown`, `&` al final, `crontab`, `at`, `systemctl --user`, servidores (`jupyter`, `http.server`, `nc -l`), túneles `ssh -R`/`-D`.
- Reescribir historia de git: `push --force`, `reset --hard`, `clean -f`, `filter-branch`.
- Ejecución opaca: `curl ... | sh`, `base64 -d | bash`, `eval "$(...)"`. Si no puedes leer lo que se ejecuta, no lo ejecutes.
- Copiar datos del cluster fuera de él (laptop, nube), salvo petición explícita de Owen para un archivo concreto y pequeño. Los datos de la competencia tienen licencia de uso.
- Modificar o desactivar el guardarraíl (`.claude/settings*.json`, `.claude/hooks/`).

## El login node

`login-01` lo comparte todo el cluster. Úsalo para editar, enviar jobs, revisar colas y leer archivos pequeños. Todo lo que tarde más de un minuto, use más de un par de GB de RAM o recorra muchos archivos va en un job:

- Entrenar, preprocesar, evaluar, convertir DICOM, comprimir o descomprimir → `sbatch`.
- `find`, `du`, `ls -R`, `tar`, `rsync`, `cp -r` sobre `kaggle_data/` (≈820k archivos) → job, o mejor, no recorrerlo: usa los conteos y la estructura de `references/entorno-yuca.md`.
- Pruebas rápidas de código → un job corto en la partición de CPU, no `python` directo.

## Protocolo para enviar jobs

1. **Escribe el script** en `jobs/` del repo a partir de `assets/job_template.slurm`. Cada job debe declarar: `-A p082`, `-J`, `--time`, memoria (`--mem` o `--mem-per-cpu`), `-o`/`-e` en `logs/` con `%j`, y `--gres=gpu:N` si usa GPU. Partición: consúltala con `ssh yuca 'sinfo -s'`, no la inventes.
2. **Revísalo con el linter:** `python .claude/hooks/check_slurm.py jobs/<script>.slurm` (o el `scripts/check_slurm.py` de esta skill; corre localmente y solo lee texto). Errores → corrige. Advertencias → son de nivel 2, pide confirmación.
3. **Commit + push.**
4. **Prueba sin enviar:** `ssh yuca 'cd /lustre/proyectos/p082/code && sbatch --test-only jobs/<script>.slurm'`. Esto valida cuenta, partición y recursos sin encolar nada.
5. **Muéstrale a Owen el resumen:** recursos (nodos, GPUs, CPUs, memoria, tiempo), qué lee, dónde escribe y cuánto espacio estimas que ocupará la salida.
6. **Envía** y anota el JOBID. La salida va siempre a `runs/$SLURM_JOB_ID/` (directorio nuevo): así nunca se pisan resultados de otro job.
7. **Monitorea con moderación.** `squeue`/`sacct` como mucho cada 60 s; cada consulta le pega al controlador de SLURM de todos. No hagas bucles de reenvío: si un job falla, lee el log, diagnostica y propón el arreglo.

## Datos y almacenamiento

- `kaggle_data/` es de **solo lectura**. Léelo desde jobs. Nada se escribe ahí, ni temporales.
- Salidas en `preproc/`, `runs/`, `logs/`, siempre en subdirectorios nuevos. Antes de escribir algo grande, revisa la cuota (`ssh yuca 'lfs quota -h -g p082 /lustre'`): el proyecto tiene 700 GB y el dataset ocupa ~570 GB. Si la salida estimada pasa de 20 GB, es nivel 2.
- Lustre es lento con muchos archivos pequeños: prefiere shards (npz, HDF5, WebDataset) sobre miles de PNG sueltos.
- El `/scratch` de cada nodo se purga cada 7 días y no se ve desde el login: úsalo solo dentro del job y copia los resultados de vuelta a Lustre antes de que termine.
- En scripts, protege las variables de rutas: `rm -- "${OUT:?}/tmp.bin"`, nunca `rm -rf $OUT/`. Si `$OUT` queda vacío, la segunda forma borra desde la raíz.

## Git

- Nunca agregues datos, checkpoints ni logs al repo (están en `.gitignore`; revisa `git status` antes de cada commit).
- No uses `git add -A` fuera de `code/`.
- Mensajes de commit descriptivos: Owen y su equipo revisan qué cambió el agente leyendo el historial.

## Cuando algo sale mal

1. **Para.** No intentes arreglar un error con una acción más fuerte (borrar, cambiar permisos, reenviar en bucle).
2. **Reporta** qué comando corriste, qué esperabas, qué pasó y el estado actual.
3. **Problemas de nodo** (GPU que no responde tras un OOM, `amdgpu` en estado raro, nodo `drain`): no reintentes en el mismo nodo. Propón reenviar con `--exclude=<nodo>` y avisar a los administradores.
4. Si un comando hizo algo inesperado, **no lo "deshagas" con otro comando destructivo**. Describe la situación y deja que Owen decida.

## El guardarraíl técnico

Estas instrucciones dependen de que las sigas; el hook `scripts/guard_hook.py` las hace cumplir. Revisa cada comando antes de ejecutarlo y responde `deny` (nivel 3) o `ask` (nivel 2, Owen confirma en un diálogo).

Si el hook bloquea un comando:

- **No lo reformules para esquivarlo** (otro quoting, variables, `bash -c`, un script intermedio). Esquivar el guardarraíl es exactamente la falla que existe para prevenir.
- Explícale a Owen qué intentabas hacer y por qué se bloqueó. Si la acción es legítima, él la ejecuta a mano o ajusta la regla.

Si Owen te pide cambiar el hook, edita la copia de la skill (no la instalada), corre `python scripts/test_guard.py` y que él la copie a `.claude/hooks/`.

El hook es una defensa adicional, no la única: atrapa patrones conocidos, no intenciones. Que un comando pase el hook no lo hace seguro; sigue clasificando cada acción con la tabla de arriba.
