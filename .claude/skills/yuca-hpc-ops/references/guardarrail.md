# Instalar el guardarraíl

La skill dice *qué* hacer; el guardarraíl hace cumplir lo crítico aunque el modelo se equivoque. Son tres capas, de la más débil a la más fuerte:

1. **Instrucciones** (SKILL.md): el modelo decide bien la mayoría de las veces.
2. **Hook + permisos de Claude Code** (este archivo): revisa cada comando antes de ejecutarlo.
3. **Permisos de Unix en el cluster**: lo único que el agente no puede saltarse, porque actúa como `owen` y `owen` no puede hacer lo que Unix le niega.

Instala las tres. Ninguna es suficiente sola.

## Capa 2: hook y permisos (en la laptop, dentro del clon del repo)

Desde la raíz del clon local (`$HOME\p082-code`):

```powershell
mkdir .claude\hooks -Force
copy <ruta-de-la-skill>\scripts\guard_hook.py  .claude\hooks\
copy <ruta-de-la-skill>\scripts\check_slurm.py .claude\hooks\
copy <ruta-de-la-skill>\assets\settings.json   .claude\settings.json
```

Si ya existía `.claude\settings.json`, combina a mano las secciones `permissions` y `hooks` en vez de sobrescribirlo.

Comprueba que funciona **antes** de usarlo:

```powershell
'{"tool_name":"Bash","tool_input":{"command":"ssh yuca ''rm -rf /lustre/proyectos/p082/kaggle_data''"}}' | python .claude\hooks\guard_hook.py
```

Debe imprimir un JSON con `"permissionDecision": "deny"`. Si no imprime nada o da error de Python, revisa que `python` en el PATH sea Python 3.9+.

Luego, dentro de Claude Code, ejecuta `/hooks`: debe aparecer el `PreToolUse` del proyecto.

Notas:

- `onFailure: "block"` hace que, si el hook no arranca (ruta mal, Python ausente), el comando se bloquee en vez de pasar. Requiere Claude Code v2.1.295 o posterior; con versiones anteriores ese campo se ignora y un hook roto deja pasar todo, así que actualiza (`claude update`).
- El hook registra cada `deny`/`ask` en `~/.claude/yuca-guard.log` (JSON por línea). Revísalo de vez en cuando para ver qué intentó hacer el agente.
- Commitea `.claude/settings.json` y `.claude/hooks/` al repo: así cada compañero que use Claude Code en el proyecto hereda el mismo guardarraíl.
- Si trabajas directo en `login-01` (cuando se resuelva lo del Fortinet), el mismo hook funciona allá; detecta el host y trata todo como "en el cluster".
- No uses `--dangerously-skip-permissions` ni el modo `bypassPermissions` en este proyecto: anulan los diálogos de confirmación de los que depende el nivel 2.

## Capa 3: blindar el dataset en el cluster

El dataset es de `owen`, así que el agente, actuando como `owen`, **podría** borrarlo aunque el grupo sea de solo lectura. Quítale también la escritura al dueño. Es un comando que Owen debe correr a mano, una sola vez, como job:

```bash
#!/bin/bash
#SBATCH -A p082
#SBATCH -J blindar_dataset
#SBATCH --time=06:00:00
#SBATCH --mem=2G
#SBATCH -o blindar_%j.log
set -euo pipefail
chmod -R a-w /lustre/proyectos/p082/kaggle_data
echo "listo"
```

Con eso, `rm` y `mv` dentro del dataset fallan con "Permission denied" aunque el hook falle. Para modificarlo después hay que devolver el permiso explícitamente (`chmod -R u+w`), y el hook bloquea ese `chmod` si lo intenta el agente.

Lo más robusto: pedir a ACARUS que el dueño del dataset sea un usuario de servicio o `root`, con grupo `p082` de solo lectura. Así ni Owen ni el agente pueden borrarlo por accidente.

## Cómo lee los comandos (y falsos positivos)

El hook divide la línea en subcomandos respetando comillas. El texto entre comillas solo se trata como dato inerte cuando el verbo nunca ejecuta sus argumentos (`grep`, `rg`, `echo`, `cat`, `squeue`, `sacct`, `git` sin `-c`…; lista completa en `DATA_VERBS` de `guard_hook.py`). Así, `grep -n "srun\|sbatch" README.md` o `git commit -m "arregla sbatch"` ya no se confunden con envíos de job. Para cualquier otro verbo (`python -c`, `find -exec`, `awk`, `sed`, `xargs`, `sbatch --wrap`…) el texto entre comillas se sigue revisando como si fuera comando, igual que antes, y `$(...)`/`` `...` `` se revisan siempre, también dentro de comillas dobles. Si una comilla queda sin cerrar, el hook vuelve al análisis más conservador.

Si aparece otro falso positivo: agrega el caso a `scripts/test_guard.py` como `none`, ajusta el hook en la copia de la skill, corre las pruebas y vuelve a copiar `guard_hook.py` a `.claude/hooks/` a mano (el agente no puede editar esa carpeta).

## Qué no cubre

- **Comandos ofuscados** (variables que arman rutas, scripts generados al vuelo y luego ejecutados): el hook ve el texto, no lo que pasará. Por eso la regla de "no reformular para esquivar" vive en la skill y la capa 3 existe.
- **Contenido de los scripts del repo** que se ejecutan en el cluster: el hook revisa los `.slurm` con el linter, pero no audita cada `.py`. Revisa los diffs antes de hacer push de código que borre o mueva archivos.
- **Consumo de recursos dentro de un job aprobado**: SLURM limita lo que pediste, no lo que hace tu código con eso.
