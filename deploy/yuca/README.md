# Despliegue manual en Yuca

Esta carpeta contiene los recursos del **primer despliegue CPU de GEMA MX** en Yuca: transferencia SSH/SCP, preflight remoto, perfil SLURM/Apptainer y una prueba de humo V2.1. No contiene credenciales ni copia el SIF ya instalado en Lustre.

La carga es manual: el script local pide confirmación y `ssh`/`scp` solicitan la autenticación configurada por el usuario. No usa `sshpass`, no acepta contraseñas como argumentos y no guarda claves.

## Alcance del paquete

`upload.sh` empaqueta solo el código Nextflow, módulos, scripts `bin/`, assets, entradas de referencia Romero necesarias para el smoke y esta carpeta. No incluye `.git`, `results/`, work/cache, servicios Compose, estructuras de otras cohortes ni la imagen SIF. Cada carga crea un release nuevo en:

```text
${YUCA_BASE_DIR}/pipeline/releases/<UTC timestamp>/
```

La imagen existente debe estar disponible en:

```text
${YUCA_SIF_PATH:-${YUCA_BASE_DIR}/containers/gemamx-nf-docking-1.0.0.sif}
```

## 1. Subir fuentes desde WSL

Desde la raíz del repositorio:

```bash
export YUCA_SSH_TARGET='<usuario>@<host SSH aprobado>'
export YUCA_BASE_DIR='<raíz Lustre asignada al proyecto>'
export YUCA_SLURM_ACCOUNT='<cuenta SLURM asignada>'
export YUCA_SLURM_PARTITION='<partición CPU aprobada>'
export YUCA_SIF_PATH="${YUCA_BASE_DIR}/containers/gemamx-nf-docking-1.0.0.sif"
bash deploy/yuca/upload.sh
```

El script pregunta antes de conectarse, transfiere el tar a `pipeline/incoming/`, compara SHA-256 local/remoto, lo extrae en un directorio de release y comprueba que el SIF esperado sea legible. La sesión SSH realiza la autenticación interactiva localmente.

Al omitir `.git`, los workflows ejecutados desde el tar pueden registrar `git_commit: unknown`; los snapshots de fuentes que sube MLflow aún conservan hashes por archivo. Para enlazar cada ejecución a un commit Git directamente, usa el mismo contenido desde un clone del repositorio en Yuca o registra el identificador de release/commit en el nombre de corrida y en la bitácora del despliegue.

Usa el path de release que imprima el script; no se modifica una instalación anterior. Para hacer rollback, vuelve a entrar al release previo. No se crea ni se cambia un enlace `current` automáticamente.

## 2. Preflight en el release

Conéctate usando la cuenta autorizada por ACARUS y cambia al release impreso por el script:

```bash
ssh "${YUCA_SSH_TARGET}"
export YUCA_BASE_DIR='<raíz Lustre asignada al proyecto>'
export YUCA_SLURM_ACCOUNT='<cuenta SLURM asignada>'
export YUCA_SLURM_PARTITION='<partición CPU aprobada>'
cd "${YUCA_BASE_DIR}/pipeline/releases/<UTC timestamp>"
bash deploy/yuca/preflight.sh
```

El preflight valida Java y Nextflow en el entorno de usuario, carga `apptainer/1.5.3-3.el8` si hace falta, comprueba el SIF y sus herramientas, los XLSX/FASTA/estructuras de referencia, escritura en Lustre y la partición `cpu` visible en SLURM. No instala software ni solicita privilegios administrativos.

Si Java o Nextflow aún no están instalados, detente aquí. Instálalos en el espacio de usuario/proyecto conforme a la guía de ACARUS y fija las versiones antes de lanzar jobs. El procedimiento validado no encontró módulos de Java/Nextflow.

## 3. Smoke V2.1

El perfil ejecuta Nextflow en el host, envía procesos a SLURM con la cuenta configurada localmente y ejecuta cada proceso mediante Apptainer. `RUN_VINA` usa 4 CPU, 4 GB y hasta 16 tareas concurrentes. El overlay se carga después de los perfiles para prevalecer sobre el selector global de recursos. El perfil Yuca establece `mlflow_enabled=false`; `PUBLISH` y la escritura de resultados no dependen de MLflow.

El primer smoke **no requiere** `MLFLOW_TRACKING_URI`, no hace health check y omite `LOG_MLFLOW` y el hook de reportes. No asumas que endpoints locales o nombres de servicios Docker son accesibles desde un clúster remoto.

Para habilitar MLflow en una etapa posterior, cuando exista un endpoint aprobado y alcanzable **desde los nodos de cómputo**, configura:

```bash
export YUCA_MLFLOW_ENABLED=true
export MLFLOW_TRACKING_URI='http://<endpoint-aprobado>:5000'
export MLFLOW_HOST_URI="${MLFLOW_TRACKING_URI}"
bash deploy/yuca/run-smoke-v2-1.sh
```

Con `YUCA_MLFLOW_ENABLED=true`, el runner exige URI y respuesta `/health` antes de enviar tareas. La prueba usa tres variantes, `exhaustiveness=1`, estructuras precomputadas, `site_on_missing=centroid`, `results/smoke_v2_1/`, `publish_run_archive=false` y `webapp_restart=false`; no sobrescribe el contrato vigente de otra instalación.

Para validar solo la compilación/canales sin ejecutar procesos ni conectarse a MLflow:

```bash
bash deploy/yuca/run-smoke-v2-1.sh -stub-run
```

El smoke real produce `report.html`, `timeline.html`, `trace.tsv` y `dag.html` bajo `results/smoke_v2_1/pipeline_info/`. Consulta SLURM con `squeue -u "$USER"` y `sacct` para estados/recursos; consulta Nextflow en `.nextflow.log` y la traza.

## 4. Criterios de aceptación

- La composición carga `romero-v2,v2_1,smoke-v2-1,yuca` con `deploy/yuca/resources.config` al final.
- Nextflow usa `executor=slurm`, la partición y cuenta configuradas localmente, Apptainer activo y Docker apagado.
- El proceso `RUN_VINA` recibe `--cpu 4`; `maxForks=16` limita su concurrencia a 64 CPU.
- Slurm marca los jobs completados y los logs/resúmenes Vina se generan dentro del SIF.
- Se producen poses PDBQT, logs Vina, summaries JSON y complejos PDB.
- Los contratos y reportes del smoke se escriben debajo del release, sin modificar otros `results/data`.
- Con `mlflow_enabled=false`, el smoke no depende de la conectividad a MLflow; si se activa `YUCA_MLFLOW_ENABLED=true`, el endpoint debe responder desde el nodo de cómputo.

## 5. Límites y rollback

Esta etapa **no despliega** PostgreSQL, MLflow, Nginx, WebApp ni la API de control como jobs SLURM. Tampoco activa Boltz/ROCm/MI210. La imagen `gemamx-nf-gpu` sigue fuera de alcance hasta validar una build ROCm y una ejecución GPU real.

Si la prueba falla, conserva el release, `.nextflow.log`, trace, `sacct` y los artefactos de la tarea fallida para diagnóstico. No borres el workDir compartido mientras se investigue; `-resume` depende de él. Para volver a una versión anterior, trabaja desde su directorio de release y conserva los resultados de cada versión separados.
