# PROPUESTAS_PLATAFORMA — cambios necesarios en `Gemacont`

Regla del proyecto: **no se duplican Dockerfiles de la plataforma**. Si una
imagen no sirve, se documenta aquí y se espera aprobación. Mientras tanto,
`gemamx_nf` no rompe nada: usa imágenes por nombre y tag fijo.

Estado de cada propuesta: `PENDIENTE` · `APROBADA` · `APLICADA`.

---

## P1 — Meeko compatible en la imagen CPU — `PENDIENTE`

**Problema.** `gemamx-cpu:1.0.0` incluye `meeko==0.5.0`, que hace
`from rdkit.six import StringIO`. RDKit 2026.03.1 ya no expone `rdkit.six`:

```
ModuleNotFoundError: No module named 'rdkit.six'
```

Cualquier proceso que importe Meeko dentro de esa imagen falla.

**Impacto.** Bloquea la preparación de ligandos con Meeko en `PREP_LIGAND`.

**Opción A (aplicada localmente, temporal).** Imagen derivada en
`containers/docking/Dockerfile`: `FROM gemamx-cpu:1.0.0` +
`meeko==0.8.0` + `gemmi==0.7.5`. Verificado con el RDKit de la imagen base.
Cuesta ~40 MB y una capa.

**Opción B (recomendada a medio plazo).** Actualizar `env/cpu-lock.yml` a
`meeko>=0.8.0` y añadir `gemmi`, reconstruir `gemamx-cpu:1.1.0` y publicarla.
Cuando exista, `gemamx_nf` puede dejar de construir su imagen derivada
(`--image_docking gemamx-cpu:1.1.0`).

**Decisión solicitada.** ¿Se aprueba B para la próxima reconstrucción?

---

## P2 — Construir y publicar `gemamx-gpu:1.0.0` — `PENDIENTE`

**Problema.** El servicio `gpu-job` referencia `gemamx-gpu:1.0.0`, pero la
imagen **no existe** en el daemon (`docker images` solo muestra
`gemamx-cpu:1.0.0`). Su Dockerfile copia el contexto completo de `Gemacont/`
(`env/gpu-environment.yml`, `v2/scripts/...`), por lo que **no puede construirse
desde `gemamx_nf`**.

**Impacto.** Bloquea `--structures_mode boltz` (Fase 9). No afecta a
`precomputed` ni `esmfold`, que son los modos usados en Fases 4–5.

**Propuesta.** Construir una vez desde `Gemacont/`:

```bash
docker compose -f infra/compose.yaml --profile gpu build gpu-job
docker tag gemamx-gpu:1.0.0 gemamx-gpu:1.0.0   # ya queda con ese tag
```

y verificar `docker run --rm --gpus all gemamx-gpu:1.0.0 test-cuda`.

**Nota.** En este equipo no hay GPU NVIDIA (solo Intel UHD), así que la
verificación con `--gpus all` no es posible aquí.

---

## P3 — MLflow: raíz de artefactos por proxy — `PENDIENTE`

**Observación.** El experimento existente `GEMAMX-M1-M8` (id 2) tiene
`artifact_location = /mlflow/artifacts/2` (ruta del filesystem del servidor).
Por eso los agentes montan el volumen `gemacont-mlflow-artifacts`. Un
contenedor efímero sin ese volumen escribiría artefactos en su propio
filesystem y se perderían.

**Verificación.** Crear un experimento con `artifact_location="mlflow-artifacts:/"`
hace que el cliente suba los artefactos por HTTP
(`artifact_uri = mlflow-artifacts:/<run>/artifacts`). Probado contra el servidor
actual (MLflow 2.19.0) y limpiado después.

**Propuesta.** Que los experimentos nuevos se creen con
`artifact_location="mlflow-artifacts:/"` para no depender de volúmenes
compartidos. `gemamx_nf` ya lo hace así en `LOG_MLFLOW`.

**Decisión solicitada.** Ninguna acción en la plataforma; solo confirmar que es
aceptable que `gemamx_nf` cree su experimento con esa raíz.

---

## P4 — Nombre estable de red y puerto — `INFORMATIVA`

- Red: `gemacont_default`; servicio MLflow resoluble como `mlflow:5000`.
- Puerto publicado en el host: **5000** (`MLFLOW_HOST_PORT`).
- `HTTP 200` en `/health`, imagen `gemamx-mlflow:1.0.0`, backend Postgres.

`gemamx_nf` usa por defecto `http://host.docker.internal:5000` y, con
`--profile platform-net`, `http://mlflow:5000` sobre la red compartida.
Ninguna acción requerida.
