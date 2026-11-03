#!/usr/bin/env bash
# =============================================================================
# Continúa la validación v2_1_exh8 que se detuvo (RUN_VINA excedió el límite).
#
#   bash tests/continuar_v2_1_exh8.sh                # reanuda en segundo plano
#   bash tests/continuar_v2_1_exh8.sh --foreground   # reanuda atada a la terminal
#
# Qué hace:
#   1. Muestra el diagnóstico de la tarea que se mató (RUN_VINA PIK3CA_WT x
#      Pictilisib): fechas de sus archivos y las últimas líneas del log de Vina.
#   2. Relanza tests/run_v2_1_exh8.sh con -resume y el mismo workDir, así las 40
#      tareas ya completadas (PREP_*, DOCK_CENTER...) salen de caché.
#   3. Por defecto lo desacopla de la terminal (setsid + nohup): cerrar PowerShell
#      o WSL no mata la corrida. El log queda en results/v2_1_exh8/pipeline_info/.
#
# Importante: los límites de tiempo de Nextflow son de reloj de pared. Si el
# equipo se suspende, esas horas cuentan. Desactiva la suspensión mientras corre
# (PowerShell: powercfg /change standby-timeout-ac 0).
# =============================================================================
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TAG="v2_1_exh8"
WORK="${HOME}/gemamx-work-${TAG}"
LOGDIR="results/${TAG}/pipeline_info"
LOG="${LOGDIR}/continuar_$(date +%Y%m%d_%H%M%S).log"
FOREGROUND=0
[[ "${1:-}" == "--foreground" ]] && FOREGROUND=1

mkdir -p "${LOGDIR}"

# ── No lanzar dos corridas a la vez ──────────────────────────────────────────
if pgrep -f "main_v2_1.nf" >/dev/null 2>&1; then
    echo "✗ Ya hay un 'nextflow run main_v2_1.nf' en ejecución:" >&2
    pgrep -af "main_v2_1.nf" | sed 's/^/    /' >&2
    echo "  Espera a que termine o detenlo antes de continuar." >&2
    exit 1
fi

# ── 1. Diagnóstico de la tarea que excedió el límite ─────────────────────────
echo "▶ Diagnóstico de RUN_VINA (PIK3CA_WT_x_Pictilisib), la tarea que excedió el límite"
found=0
for d in "${WORK}"/ed/f8779d2c*; do
    [[ -d "$d" ]] || continue
    found=1
    echo "  workDir: $d"
    ls -la --time-style=long-iso "$d" | sed 's/^/    /'
    for f in "$d"/*_vina.log; do
        [[ -f "$f" ]] || continue
        echo "  --- $(basename "$f") (últimas líneas)"
        tail -n 12 "$f" | sed 's/^/    /'
    done
    if [[ -f "$d/.command.log" ]]; then
        echo "  --- .command.log (últimas líneas)"
        tail -n 5 "$d/.command.log" | sed 's/^/    /'
    fi
done
if [[ "$found" -eq 0 ]]; then
    echo "  (el directorio de trabajo ya no existe: no hay nada que diagnosticar)"
fi
echo "  Si el log de Vina quedó a medias o sus fechas están muy separadas, la tarea"
echo "  se colgó o el equipo se suspendió; no es solo falta de tiempo."
echo

# ── 2. Reanudar ──────────────────────────────────────────────────────────────
echo "▶ Reanudando con -resume (workDir: ${WORK})"
if [[ "$FOREGROUND" -eq 1 ]]; then
    exec bash tests/run_v2_1_exh8.sh -resume -ansi-log false
fi

setsid nohup bash tests/run_v2_1_exh8.sh -resume -ansi-log false > "${LOG}" 2>&1 &
PID=$!
sleep 3
if kill -0 "${PID}" 2>/dev/null; then
    echo "  ✓ Corrida en segundo plano (PID ${PID})"
else
    echo "  ✗ El proceso terminó de inmediato; revisa ${LOG}" >&2
    tail -n 20 "${LOG}" >&2 || true
    exit 1
fi
echo "  Log:           ${LOG}"
echo "  Seguirlo:      tail -f ${LOG}"
echo "  Ver progreso:  grep -c 'RUN_VINA' ${LOG}"
echo "  Cuando termine, el análisis queda en results/${TAG}/pipeline_info/analisis.txt"
