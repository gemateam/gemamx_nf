# ALMACENAMIENTO — dónde vive el resultado de cada módulo y de cada corrida

Decisión de arquitectura: **tres capas con responsabilidades distintas** y
**sin MongoDB**. Este documento fija qué escribe cada proceso, qué se conserva y
qué se puede borrar sin perder trazabilidad.

---

## 1. Las tres capas

| Capa | Ruta por defecto | Contenido | Vida útil | Consumidor |
|---|---|---|---|---|
| **Caché de ejecución** | `~/gemamx-work` (`params.work_dir`) | Salidas intermedias de cada tarea, en directorios por hash (`work/ab/cdef…/`) | Efímera; existe para `-resume` | Solo Nextflow |
| **Archivo por corrida** | `<outdir>/runs/<runName>/` | Copia inmutable de todo lo publicado por esa corrida + `run_manifest.json` | Permanente (auditoría) | Personas / auditoría |
| **Contrato vigente** | `<outdir>/data/` | Los seis JSON de contrato, estructuras y docking de la **última corrida exitosa** | Se sobrescribe al publicar | La app web |
| **Tracking** | Servidor MLflow (`params.mlflow_tracking_uri`) | Parámetros, métricas, tags y artefactos pequeños por corrida y por variante | Histórico | Dashboard / comparación |

`work/` **no** es un entregable: sus nombres son hashes y su contenido se
invalida al cambiar el código. Nunca se documenta una ruta de `work/` como
resultado.

## 2. Qué escribe cada proceso

| Proceso | Intermedio (`work/`) | Publicado (`runs/<runName>/` y `data/`) | MLflow |
|---|---|---|---|
| `INGEST` | `raw_mutations.json`, `top_variants.json` | `data/raw_mutations.json`, `data/top_variants.json` | params + nº de variantes y muestras |
| `FETCH_FASTA` | `<gen>_WT.fasta`, `<gen>_<cambio>.fasta` + sidecar | `data/fasta/` | — |
| `PREDICT_STRUCTURE` | `<gen>_<cambio>.pdb` + `.json` (pLDDT, `start`, `end`, `offset`) | `data/structures/` | `plddt_mean` |
| `ALIGN_WT_MUT` | `rmsd.json` | — | `rmsd_global`, `rmsd_active` |
| `PREP_LIGAND` | `<fármaco>.pdbqt` | `data/docking/ligands/` | — |
| `PREP_RECEPTOR` | `<receptor>.pdbqt` | `data/docking/receptors/` | — |
| `DOCK_CENTER` | `box.json` | — | params de la caja |
| `RUN_VINA` | `<var>_<fármaco>_out.pdbqt`, `_log.txt` | `data/docking/results/`, `data/docking/complex/` | `vina/<fármaco>` (kcal/mol) |
| `BUILD_JSONS` | — | `runs/<runName>/data/`: `structural_metrics.json`, `vina_affinities.json`, `manifest_structures.json`, `mutation_stats.json` | artefactos JSON |
| `PUBLISH` | — | `runs/<runName>/run_manifest.json` (params, commit, checksums). No toca `data/` | — |
| `publish_contract.py` (host) | — | promoción atómica de `runs/<runName>/data` a `data/`, `runs/index.json` y copia del manifiesto | — |
| `LOG_MLFLOW` | — | — | run padre + hijas anidadas + artefactos |

`PUBLISH` es el único proceso con `publishDir`: no calcula nada, solo sella la
corrida en `runs/<runName>/` (ver §4). El resto de las rutas de la columna
«Publicado» llegan al contrato a través de ese árbol, no directamente a `data/`.

### Qué NO se sube a MLflow

Estructuras, receptores y poses completas. Pesan (decenas de MB por corrida) y
ya están en `outdir`; a MLflow van los JSON, los logs de Vina y un tag con la
ruta y el checksum. Así el servidor de tracking no se convierte en un almacén
de gigabytes.

## 3. Layout de `--outdir`

```
results/
├── data/                             # contrato vigente (lo que sirve la app)
│   ├── top_variants.json
│   ├── structural_metrics.json
│   ├── manifest_structures.json
│   ├── raw_mutations.json
│   ├── mutation_stats.json
│   ├── structures/
│   └── docking/
│       ├── vina_affinities.json
│       ├── results/
│       └── complex/
├── runs/
│   ├── index.json                    # una entrada por corrida archivada
│   └── <runName>/                    # inmutable, una por corrida
│       ├── data/…                    # misma estructura que data/
│       └── run_manifest.json         # params + commit + checksums + fecha
├── run_manifest.json                 # copia del manifiesto de la corrida vigente
└── pipeline_info/
    ├── <runName>/{report.html,trace.tsv,timeline.html,dag.html}
    └── publish.log                   # salida de la promoción (acumulativa)
```

- `<runName>` es `workflow.runName` (por defecto Nextflow genera uno del tipo
  `adjective_scientist`; se puede fijar con `-name`). Es también el nombre del
  run padre en MLflow, lo que hace trivial cruzar disco ↔ MLflow.
- `run_manifest.json` **no** es un contrato: es un archivo extra de
  provenance. No lo consume la app.

## 4. Promoción a `data/` (corrida vigente)

El proceso `PUBLISH` **no escribe en `data/`**: `publishDir` copia el árbol de la
corrida a `runs/<runName>/data` (y su `run_manifest.json` a
`runs/<runName>/`). Esa copia es inmutable: cada corrida escribe la suya y nunca
reescribe la de otra.

La promoción la hace `bin/publish_contract.py`, lanzado desde
`workflow.onComplete` mediante `bin/publish_contract_hook.sh`. Corre en el
**host** (no en un contenedor, que no vería las rutas del outdir) y solo si la
corrida terminó bien:

1. valida que `runs/<runName>/data` tenga los seis contratos; si falta alguno
   sale con código 2 y **no toca nada**;
2. copia el árbol completo a `data.tmp/`;
3. lo sustituye con dos `rename` dentro del mismo filesystem
   (`data/` → `data.old/`, `data.tmp/` → `data/`, y borra `data.old/`), de modo
   que la app nunca vea un árbol a medias: o el anterior completo, o el nuevo
   completo;
4. copia `run_manifest.json` a `<outdir>/` y a `<outdir>/data/` (la app lo lee
   de `data/`);
5. con `publish_run_archive = true` conserva `runs/<runName>/` y añade o
   reemplaza su entrada en `runs/index.json`; con `false` (perfiles de humo)
   borra `runs/<runName>/` tras promover y no toca el índice;
6. con `webapp_restart = true` ejecuta `docker restart <webapp_container>`: el
   `rename` deja el bind mount de nginx apuntando al inodo anterior, así que sin
   reinicio la webapp seguiría sirviendo el contrato viejo. Si el reinicio falla
   solo se avisa; la promoción ya está hecha.

Si la promoción falla, se restaura el árbol anterior y el script sale con
código 3: la app sigue sirviendo la corrida anterior. Una corrida `-stub-run`
no promueve nada.

`webapp_restart` está desactivado en los perfiles `smoke` y `smoke-v2-1` porque
publican en `results/smoke*`, no en el `data/` que sirve la webapp.

## 5. Retención

| Qué | Política |
|---|---|
| `work/` | Se conserva mientras se valida la corrida (`-resume`). Purga: `nextflow clean -before <runName>`. |
| `runs/<runName>/` | Se conserva indefinidamente (pesa poco: ~0.3–1 MB de estructuras y ~15 MB de docking por variante). |
| `data/` | Solo la última corrida exitosa. |
| MLflow | Metadatos indefinidos; la retención de artefactos se configura en el servidor. |

**Rendimiento:** `work_dir` y, para corridas completas, `outdir` deben estar en
el filesystem Linux (ext4). Publicar sobre `/mnt/d` (9p) es correcto pero lento
con muchos archivos pequeños; el perfil `test` puede escribir ahí sin problema.

## 6. MongoDB: descartado

En el legado, MongoDB era un **cuaderno de trabajo**, no una base de datos de
producto:

- `ingest_data.py` insertaba en las colecciones `mutations` y `top_variants`;
- `fetch_fasta.py` insertaba en `fasta_sequences`;
- `export_db.py` volcaba esas colecciones a JSON, que es lo que la app consume.

Es decir, la base estaba **antes** de los JSON de contrato. En Nextflow cada
colección pasa a ser la salida de una tarea que viaja por un canal, y el JSON es
la única fuente de verdad.

Motivos para no habilitarlo:

1. **Doble fuente de verdad**: escribir en base y en archivos abre la puerta a
   que discrepen.
2. **No participa en `-resume`**: Nextflow cachea por archivos, no por base de
   datos.
3. **Servicio stateful innecesario**: contenedor, volumen, backup y credenciales
   en un equipo con 7.6 GB de RAM.
4. **Rompe el aislamiento**: el pipeline debe poder correr sin backend de
   escritura (igual que `RUN_VINA` no escribe MLflow).
5. **No hay consultas que lo justifiquen**: la app es estática y lee seis JSON.

**Cuándo reconsiderarlo:** si la app deja de ser estática y necesita API con
filtros o escrituras concurrentes sobre las 60,864 mutaciones. Eso sería un
backend de plataforma alimentado *después* del pipeline desde los JSON, y se
documentaría como propuesta de arquitectura aparte, no aquí.
