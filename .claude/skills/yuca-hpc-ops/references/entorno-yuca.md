# Entorno del cluster Yuca

Contexto fijo del cluster y del proyecto p082. Si algo de aquí contradice lo que ves en el cluster (`sinfo`, `ls`, `lfs quota`), créele al cluster y avísale a Owen para actualizar este archivo.

## Acceso

- Login node: `login-01`, host `yuca.unison.mx`, usuario `owen`.
- Desde la laptop de Owen (Windows): alias `yuca` en `~/.ssh/config`. La llave vive en el agente SSH de Bitwarden; si `ssh yuca` pide contraseña o falla con "agent refused", es que la bóveda está bloqueada: pídele a Owen que la desbloquee, no intentes otras credenciales.
- En Windows nativo no hay `ControlMaster`: cada `ssh yuca '...'` abre una conexión nueva (~1 s). Agrupa comandos de lectura en una sola llamada cuando tenga sentido.

## Hardware

| Componente | Detalle |
|---|---|
| CPU | AMD EPYC |
| GPU | AMD Instinct MI210, `gfx90a`, 64 GB VRAM c/u |
| Stack GPU | ROCm 7.2.x — **no CUDA**. PyTorch debe ser build ROCm |
| Scheduler | SLURM |
| Nodos vistos | `amdgpu-hpc-02` (GPU), `amdcpu-hpc-01`, `amdcpu-hpc-03` (CPU) |
| Particiones | Al menos `cpu`; la de GPU confírmala con `sinfo -s` |

## Almacenamiento

| Ruta | Qué es | Notas |
|---|---|---|
| `/lustre/home/owen` | Home de Owen | Lustre, persistente |
| `/lustre/proyectos/p082` | Directorio compartido del proyecto | 700 GB de cuota (grupo `p082`), setgid + sticky |
| `/lustre/proyectos/p082/kaggle_data` | Dataset RSNA Knee crudo | **Solo lectura.** 819,640 archivos, ~570 GB, DICOM + CSV. Dueño `owen`, grupo `p082` |
| `/lustre/proyectos/p082/code` | Repo git del proyecto | `receive.denyCurrentBranch updateInstead` |
| `/lustre/proyectos/p082/envs`, `nllb` | De jcastro | **No tocar** |
| `preproc/`, `runs/`, `logs/` | Salidas del equipo | Crear subdirectorios nuevos por job |
| `/scratch` en nodos de cómputo | Disco local (~720 GB) | Invisible desde el login; **se purga cada 7 días** |

Estructura del dataset: `kaggle_data/competitions/rsna-knee-abnormality-detection/` con `test_series/`, los CSV de etiquetas y los directorios de train. No recorras el árbol completo para descubrirlo; lista un nivel a la vez.

Lustre penaliza los muchos archivos pequeños: un `find` sobre `kaggle_data` tarda minutos y carga los servidores de metadatos de todos los usuarios.

## Red

UniSon pasa todo el HTTPS por un **Fortinet con inspección SSL** (CA `CN=F2K60FTK21900908, O=Fortinet`), tanto en el login como en los nodos de cómputo. Síntomas: `SSL certificate problem: unable to get local issuer certificate`, `CERTIFICATE_VERIFY_FAILED`, `curl: (60)`.

- Owen todavía **no tiene** el certificado de esa CA (los `.pem` de su home no sirven: uno está vacío y el otro es un certificado hoja de huggingface.co).
- La solución es que los administradores instalen la CA en el sistema (`/etc/pki/ca-trust/source/anchors/` + `update-ca-trust`) o que exceptúen ciertos dominios de la inspección.
- Mientras tanto: las descargas desde el cluster pueden fallar. **No desactives la verificación.** Reporta el error y propón alternativas (descargar fuera y subir con `scp`, o esperar la CA).

## Equipo y propiedad

- Proyecto SLURM: `p082`, "Competencia de Kaggle RSNA Knee Abnormality Detection", responsable Victor Manuel Minjares Neriz.
- Owen (`owen`) es colaborador y además opera el cluster en ACARUS, pero **tú no actúas como administrador**: nada de tareas de admin aunque él tenga contexto para hacerlas.
- `jcastro` es otro miembro; sus directorios no son tuyos.

## Lecciones previas

- Descargas o procesos largos siempre como job; las sesiones SSH se caen.
- Un OOM en GPU puede dejar `amdgpu` del nodo en estado inconsistente: reportar a admins, excluir el nodo.
- Antes de instalar PyTorch en un entorno, verifica la versión de ROCm del nodo (`rocminfo`, `rocm-smi`) dentro de un job en el nodo GPU.
