#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SSH_TARGET="${YUCA_SSH_TARGET:?Define YUCA_SSH_TARGET localmente antes de transferir}"
BASE_DIR="${YUCA_BASE_DIR:?Define YUCA_BASE_DIR según las instrucciones de tu sitio}"
RELEASE_ID="${YUCA_RELEASE_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
REMOTE_RELEASE="${BASE_DIR}/pipeline/releases/${RELEASE_ID}"
REMOTE_INCOMING="${BASE_DIR}/pipeline/incoming"
SIF_PATH="${YUCA_SIF_PATH:-${BASE_DIR}/containers/gemamx-nf-docking-1.0.0.sif}"
ARCHIVE_NAME="gemamx-yuca-${RELEASE_ID}.tar.gz"

for command in tar ssh scp sha256sum; do
    if ! command -v "${command}" >/dev/null 2>&1; then
        printf 'Falta el comando requerido: %s\n' "${command}" >&2
        exit 2
    fi
done

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT
ARCHIVE="${TMP_DIR}/${ARCHIVE_NAME}"

printf 'Empaquetando fuentes para %s\n' "${SSH_TARGET}"
tar -czf "${ARCHIVE}" -C "${ROOT}" \
    LICENSE README.md \
    main.nf main_v2.nf main_v2_1.nf main_v3.nf \
    nextflow.config nextflow_schema.json \
    conf assets modules bin \
    tests/run_smoke_v2_1.sh \
    tests/reference/romero_v2/raw \
    tests/reference/romero_v2/fasta \
    tests/reference/romero_v2/structures \
    docs/V2_1.md docs/BOLTZ_HPC.md \
    deploy/yuca

LOCAL_SHA="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
printf 'Paquete: %s (%s bytes)\nSHA-256 local: %s\nDestino: %s:%s\n' \
    "${ARCHIVE_NAME}" "$(stat -c %s "${ARCHIVE}")" "${LOCAL_SHA}" \
    "${SSH_TARGET}" "${REMOTE_RELEASE}"

if ! read -r -p '¿Transferir este release? [y/N] ' answer; then
    answer=""
fi
if [[ ! "${answer}" =~ ^[Yy]$ ]]; then
    printf 'Cancelado; no se conectó al servidor.\n'
    exit 0
fi

REMOTE_ARCHIVE="${REMOTE_INCOMING}/${ARCHIVE_NAME}"
ssh "${SSH_TARGET}" "mkdir -p '${REMOTE_INCOMING}' '${REMOTE_RELEASE}'"
scp "${ARCHIVE}" "${SSH_TARGET}:${REMOTE_ARCHIVE}"
REMOTE_SHA="$(ssh "${SSH_TARGET}" "sha256sum '${REMOTE_ARCHIVE}' | awk '{print \$1}'")"
if [[ "${REMOTE_SHA}" != "${LOCAL_SHA}" ]]; then
    printf 'ERROR: SHA-256 remoto no coincide; no se extraerá el paquete.\n' >&2
    printf 'local=%s\nremoto=%s\n' "${LOCAL_SHA}" "${REMOTE_SHA}" >&2
    exit 3
fi

ssh "${SSH_TARGET}" "tar -xzf '${REMOTE_ARCHIVE}' -C '${REMOTE_RELEASE}' && test -r '${SIF_PATH}'" || {
    printf 'El paquete llegó, pero falta el SIF esperado o falló la extracción:\n%s\n' "${SIF_PATH}" >&2
    exit 4
}

printf '\nRelease instalado y checksum verificado.\n'
printf 'Siguiente paso en Yuca:\n  ssh %s\n  cd %s\n  bash deploy/yuca/preflight.sh\n' \
    "${SSH_TARGET}" "${REMOTE_RELEASE}"
