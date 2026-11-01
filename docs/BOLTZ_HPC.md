# Boltz-1 en HPC (YUCA / ACARUS-UNISON) — módulo implementado, ejecución pendiente

`structures_mode = 'boltz'` está **implementado y documentado**, pero **no se
ejecuta en el equipo de desarrollo** (sin GPU). Está preparado para lanzarse en
**YUCA**, el clúster de cómputo de alto rendimiento del ACARUS (UNISON).

Estado actual:

| Pieza | Ubicación | Estado |
|---|---|---|
| Procesos `BOLTZ_WT` / `BOLTZ_MUT` | `modules/structure/boltz.nf` | ✅ implementado, no ejecutado |
| Preparación del YAML de entrada | `bin/prep_boltz_yaml.py` | ✅ probado sin GPU |
| Imagen GPU con Boltz | `containers/gpu/Dockerfile` | 📄 definida, no construida |
| Perfil de ejecutor remoto | `nextflow.config` → `hpc-yuca` | 📄 plantilla, ajustar al clúster |
| Perfil GPU local | `nextflow.config` → `gpu`, `conf/gpu.config` | 📄 plantilla |
| Activación en `main.nf` | bloque comentado | 📄 documentado abajo |

---

## 1. YUCA en cifras (fuente: ACARUS, 2026)

Datos publicados en <https://acarus.unison.mx/hardware/>,
<https://acarus.unison.mx/especificaciones-tecnicas-de-yuca> y
<https://acarus.unison.mx/software/>.

| Recurso | Valor |
|---|---|
| Host / acceso | `yuca.unison.mx` · Open OnDemand <https://yucaood.acarus.unison.mx> |
| Sistema operativo | AlmaLinux 9.4 |
| Gestor de colas | **Slurm** |
| Nodos | 40 = 24 CPU + **6 GPU** + 6 virtualización + 2 maestro + 2 login |
| Nodos GPU | AMD EPYC 9224 (48 cores/nodo) + **1 AMD Instinct MI210 por nodo** |
| VRAM por nodo GPU | **64 GB HBM2e** (MI210) |
| RAM por nodo GPU | ≈ 1.1 TB (6.77 TB entre los 6 nodos) |
| Cómputo GPU | 288 cores CPU + 6656 stream processors en total |
| Almacenamiento | 2.8 PB HDD + 450 TB SSD |
| Límite por grupo | **320 cores simultáneos**, walltime **máximo 168 h (7 días)** |
| Prioridad | Usuarios UNISON primero; externos solo si no hay trabajos encolados |

**Software ya instalado en YUCA** (relevante para este pipeline):

| Paquete | Versión | Uso en gemamx_nf |
|---|---|---|
| `apptainer` | 1.3.6 | ejecución de contenedores (no hay Docker) |
| `rocm` | 6.2.3 | stack GPU de las MI210 |
| `autodock-vina` | **1.1.2** | alternativa nativa a `RUN_VINA` en contenedor |
| `autodock` | 4.2.6 | utilidades de receptor/ligando |
| `gromacs` | 2025.2 | no usado hoy (futuro MD) |
| `openMPI` | 5.0.7 | paralelismo MPI |
| `conda` / `python` | 24.11.1 / 3.12.8 | entorno de los scripts `bin/*.py` |

> **Consecuencia directa:** la parte de docking del pipeline (`RUN_VINA`, que hoy
> usa la imagen `gemamx-nf-docking:1.0.0`) puede correr en YUCA **sin
> contenedor**, usando el `autodock-vina 1.1.2` del módulo del clúster. La parte
> que necesita GPU es solo `BOLTZ_WT/BOLTZ_MUT`.

### La GPU no es NVIDIA

Las 6 MI210 son **AMD (ROCm 6.2.3)**, no CUDA. Boltz-1 se publica y se valida
en CUDA, así que hay tres caminos, en este orden:

| Plan | Qué hacer | Riesgo |
|---|---|---|
| **A. ROCm** | Imagen base ROCm + PyTorch ROCm; `boltz predict --accelerator gpu` (torch mapea a HIP) | medio: dependencias opcionales de Boltz (`cuequivariance`) son CUDA-only y habría que desinstalarlas/evitarlas |
| **B. CPU** | `boltz predict --accelerator cpu` sobre los 48 cores del nodo | bajo; viable porque solo se pliega la ventana (202 aa), pero 10–40 min por estructura |
| **C. Pitaya** | Nodo único con **NVIDIA L4 24 GB** (64 cores, 1 TB RAM, Ubuntu 22.04) | bajo, pero es un servidor dedicado a PLN/LLM: hay que pedir acceso |

Pitaya **no** es un nodo de Slurm de YUCA (`148.225.111.151`), es un servidor
aparte; si se usa, el perfil sería `local` sobre esa máquina, no `slurm`.

### Solicitud de acceso

- Cuenta: <https://acarus.unison.mx/solicitud-de-cuentas-2/> (proyecto + grupo).
- Guía de usuario: <https://acarus.unison.mx/guia-de-usuario/>.
- Colas y límites: <https://acarus.unison.mx/administracion-de-colas-con-slurm/>.

---

## 2. Requisitos del módulo

**Hardware**

- GPU con **≥ 16 GB de VRAM**; en la práctica YUCA ofrece 64 GB (MI210), así que
  la ventana de dominio se puede ampliar sin problema.
- **32–64 GB de RAM** (YUCA tiene ~1 TB por nodo) y **~30 GB de disco** por
  corrida (pesos de Boltz, caché de MSA y salidas).
- Salida a internet **o** MSA precalculado (ver § 6).

**Software**

- Nextflow 25/26 + Java 17 en el nodo de login.
- **Apptainer 1.3.6** (ya instalado en YUCA). No hay daemon Docker.
- Imagen con `boltz` en el `PATH` (ver § 3).

---

## 3. Imagen

`containers/gpu/Dockerfile` parte de `gemamx-gpu:1.0.0` (imagen GPU de la
plataforma) y fija la versión de Boltz validada. La imagen base se puede
cambiar con `--build-arg BASE_IMAGE=...` para el caso ROCm.

```bash
docker build \
    --build-arg BOLTZ_VERSION=<versión-validada> \
    -t gemamx-nf-gpu:1.0.0 containers/gpu

docker run --rm --gpus all gemamx-nf-gpu:1.0.0 boltz --help
```

En YUCA no se usa Docker: se convierte a **SIF** y se ejecuta con Apptainer.

```bash
# En el nodo de login (o en cualquier host con apptainer)
apptainer build gemamx-nf-gpu_1.0.0.sif docker-daemon://gemamx-nf-gpu:1.0.0
# o, si la imagen está en un registro:
apptainer build gemamx-nf-gpu_1.0.0.sif docker://<registro>/gemamx-nf-gpu:1.0.0

# Prueba en un nodo GPU (--rocm monta los dispositivos AMD; --nv sería para NVIDIA)
srun -p <cola-gpu> --gres=gpu:1 apptainer exec --rocm gemamx-nf-gpu_1.0.0.sif boltz --help
```

Si la imagen de la plataforma `gemamx-gpu:1.0.0` ya trae Boltz, se puede usar
directamente con `--image_gpu gemamx-gpu:1.0.0` y no hace falta esta capa.

---

## 4. Cómo funciona el módulo

```
FASTA (FETCH_FASTA)
   └─ prep_boltz_yaml.py      → YAML de Boltz + sidecar (model_start/end, resSeq de la mutación)
        └─ boltz predict       → out_dir/**/ *_model_0.cif   (mejor modelo)
             └─ predict_structure.py --backend precomputed
                                   → PDB normalizado + sidecar JSON + mmCIF
```

La normalización final reutiliza `bin/predict_structure.py`, así que la salida
tiene **exactamente la misma forma** que `PREDICT_STRUCTURE_WT/MUT`:
`ALIGN_WT_MUT`, `PREP_RECEPTOR`, `DOCK_CENTER`, `RUN_VINA` y `BUILD_JSONS` no
cambian.

`prep_boltz_yaml.py` aplica la mutación a la secuencia y recorta la **misma
ventana** que ESMFold (`params.domain_window`), de modo que WT y MUT cubren la
misma región y el RMSD es comparable con `precomputed`.

Probarlo sin GPU (solo genera el YAML):

```bash
python3 bin/prep_boltz_yaml.py \
    --fasta tests/reference/fasta/PIK3CA.fasta \
    --gene PIK3CA --protein-change H1047R --role mut \
    --window 180 --out-yaml /tmp/boltz_mut.yaml --out-meta /tmp/boltz_mut.json
```

---

## 5. Activación en el pipeline

El módulo **no está cableado por defecto**: `PREDICT_STRUCTURE_WT/MUT` siguen
siendo el camino activo y `structures_mode = 'boltz'` falla con un mensaje
explícito que apunta a este documento.

Para activarlo en un clúster con GPU, en `main.nf`:

```groovy
// 1) include
include { BOLTZ_WT; BOLTZ_MUT } from './modules/structure/boltz.nf'

// 2) sustituir las dos llamadas de predicción
//    PREDICT_STRUCTURE_WT(ch_wt_struct_input)
//    PREDICT_STRUCTURE_MUT(ch_mut_struct_input)
BOLTZ_WT(FETCH_FASTA_WT.out.wt_fasta.join(ch_gene_center))
BOLTZ_MUT(FETCH_FASTA_MUT.out.mut_fasta.map { gene, pc, fasta -> tuple(gene, pc, fasta) })
```

`BOLTZ_WT` recibe el centro de ventana por gen (`ch_gene_center`, la primera
mutación conocida), igual que la rama ESMFold. `BOLTZ_MUT` recibe
`[gene, protein_change, fasta]`.

Después:

```bash
nextflow run . -profile hpc-yuca --structures_mode boltz -resume
```

---

## 6. Perfil `hpc-yuca`

Plantilla en `nextflow.config` (bloque `profiles { 'hpc-yuca' { ... } }`).
**Ajustar antes del primer uso**:

| Ajuste | Valor actual | Qué comprobar en YUCA |
|---|---|---|
| `executor = 'slurm'` | ✅ correcto | — |
| `queue = 'gpu'` | suposición | `sinfo -s` para el nombre real de la partición GPU |
| `clusterOptions` | vacío | `-A <proyecto>` / `--partition` si aplica |
| `apptainer.runOptions` | `--rocm` | `--rocm` para MI210 (AMD); `--nv` si se usa Pitaya/NVIDIA |
| `apptainer.cacheDir` | por defecto | carpeta con cuota en el `$HOME` o `$SCRATCH` |
| `params.image_gpu` | `gemamx-nf-gpu:1.0.0` | ruta completa del `.sif` |
| `params.mlflow_tracking_uri` | `http://127.0.0.1:5000` | túnel SSH al MLflow local, o desactivar |
| `resourceLimits` | 16 CPU / 128 GB / 24 h | el límite duro del clúster es 320 cores y 168 h |

MSA:

- `params.boltz_use_msa_server = true` (por defecto) usa el servidor público de
  ColabFold: requiere salida a internet desde el nodo GPU.
- En un nodo aislado: poner `false` y precalcular el MSA con MMseqs2 local,
  pasándolo en el YAML (`msa: <ruta.a3m>` en vez de `msa: empty`).

---

## 7. Coste esperado (estimación, sin validar)

| Paso | Tiempo aproximado |
|---|---|
| Generación de MSA (servidor) | 1–5 min por secuencia |
| `boltz predict` (202 aa, 1 GPU) | 2–6 min |
| WT + MUT (`maxForks = 1`, secuencial) | 10–25 min |
| Misma pareja en **CPU** (plan B) | 20–80 min |

El resto del pipeline (docking) domina el tiempo total en el perfil `test`.

---

## 8. Limitaciones conocidas

- **No ejecutado**: ni el módulo ni la imagen se han probado con GPU real. La
  primera ejecución en YUCA debe hacerse con `-stub-run` para validar el
  cableado y después con una sola variante.
- **GPU AMD**: Boltz-1 se publica para CUDA. En las MI210 (ROCm 6.2.3) hay que
  validar el plan A; si falla, usar el plan B (CPU) o pedir acceso a Pitaya.
- **Versión de Boltz**: hay que fijarla (`--build-arg BOLTZ_VERSION=...`) a la
  que se valide en el clúster; no se asume ninguna.
- **pLDDT**: Boltz escribe la confianza en el B-factor del mmCIF; se reescala a
  0–100 igual que ESMFold/AlphaFold.
- **Ventana de dominio**: para proteínas largas se pliega solo la ventana
  (± `params.domain_window`). Con 64 GB de VRAM se puede subir
  `domain_window` y plegar PIK3CA completa (1068 aa), a cambio de más tiempo.

---

## 9. Reversión

Volver al camino sin GPU es dejar `main.nf` como está hoy y ejecutar con
`-profile docker,test` (o `--structures_mode esmfold`). No hay estado oculto:
el modo se elige por parámetro y el contrato de salida es idéntico.
