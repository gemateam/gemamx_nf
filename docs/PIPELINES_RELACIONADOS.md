# Pipelines y herramientas relacionadas

Proyectos de la comunidad Nextflow y de oncología genómica que complementan o se relacionan con GEMA MX. Ninguno forma parte del pipeline actual; este documento sirve como mapa de referencia para posibles extensiones (tipificación HLA, neoantígenos y anotación clínica).

> Información verificada en las páginas oficiales de cada proyecto el 2026-11-01. Las versiones y el estado de mantenimiento pueden cambiar; confirmar en el enlace de cada proyecto antes de integrar.

## Resumen

| Proyecto | Qué hace | Usa Nextflow | Licencia / Cita | Relación con GEMA MX |
|---|---|---|---|---|
| [NeoFlow](https://github.com/bzhanglab/neoflow) | Descubrimiento de neoantígenos por proteogenómica | Sí (4 scripts `.nf`) | [Wen et al., *Nat Commun* 2020](https://doi.org/10.1038/s41467-020-15456-w) | Variantes somáticas → neoepítopos y evidencia de péptidos variantes |
| [nf-core/hlatyping](https://nf-co.re/hlatyping/2.2.0/) | Tipificación HLA a partir de secuenciación (NGS) | Sí (DSL2, nf-core) | DOI [10.5281/zenodo.1401039](https://doi.org/10.5281/zenodo.1401039) | Genotipo HLA del paciente, requisito para predecir neoantígenos |
| [WiGiTS (hmftools)](https://github.com/hartwigmedical/hmftools) | Suite de análisis de genoma y transcriptoma para investigación y diagnóstico en cáncer | Mediante [Oncoanalyser](https://nf-co.re/oncoanalyser) (nf-core) | GPL-3.0 | Llamado, anotación y accionabilidad clínica de variantes |

---

## 1. NeoFlow

**Repositorio:** <https://github.com/bzhanglab/neoflow> · **Artículo:** [doi:10.1038/s41467-020-15456-w](https://doi.org/10.1038/s41467-020-15456-w)

Pipeline de proteogenómica para el descubrimiento de neoantígenos. Está organizado en cuatro módulos, cada uno un script Nextflow independiente:

1. **Anotación de variantes y base de datos personalizada** (`neoflow_db.nf`): anota variantes con ANNOVAR y construye bases de proteínas FASTA a medida.
2. **Identificación de péptidos variantes** (`neoflow_msms.nf`): búsqueda MS/MS con MS-GF+, X!Tandem o Comet, estimación global de FDR, validación de péptidos nuevos con PepQuery y validación opcional por tiempo de retención con AutoRT (requiere GPU).
3. **Tipificación HLA** (`neoflow_hlatyping.nf`): usa OptiType.
4. **Predicción de neoantígenos** (`neoflow_neoantigen.nf`): usa netMHCpan 4.0 e integra la evidencia de péptidos variantes.

Soporta datos label-free y iTRAQ/TMT. Las herramientas están dockerizadas, salvo ANNOVAR y netMHCpan 4.0, que se instalan por separado (ambas con licencias de uso propias).

**Puntos a considerar para GEMA MX**

- Los módulos 1, 3 y 4 son los más afines: GEMA MX ya produce variantes somáticas priorizadas (`top_variants.json`) y podría extenderse a la predicción de neoepítopos.
- El módulo 2 requiere datos de espectrometría de masas, que la cohorte Romero-Córdoba (tablas MOESM) no incluye.
- Los ejemplos de uso del repositorio están documentados con Nextflow 19.10.0 (estilo anterior a DSL2). Antes de reutilizar sus procesos conviene verificar compatibilidad con Nextflow 23.10+ y DSL2, que es lo que usa este proyecto.

---

## 2. nf-core/hlatyping

**Página:** <https://nf-co.re/hlatyping/2.2.0/> · **Código:** <https://github.com/nf-core/hlatyping>

Pipeline de nf-core para la tipificación del antígeno leucocitario humano (HLA) a partir de datos de secuenciación de nueva generación, basado en [OptiType](https://github.com/FRED-2/OptiType), un algoritmo de genotipado HLA que usa programación lineal entera. Acepta lecturas de exoma, genoma o transcriptoma completos y produce genotipos de 4 dígitos para HLA clase I. Opcionalmente soporta HLA clase I+II con [HLA-HD](https://w3.genome.med.kyoto-u.ac.jp/HLA-HD/) (requiere instalación local).

**Flujo (versión 2.2.0):** concatenación de FASTQ → control de calidad (FastQC) → índices y mapeo (yara) → tipificación (OptiType / HLA-HD opcional) → reporte (MultiQC).

**Entrada:** hoja de muestras `samplesheet.csv` con columnas `sample,fastq_1,fastq_2,seq_type` (`dna` o `rna`); también acepta BAM.

```bash
nextflow run nf-core/hlatyping \
   -profile <docker/singularity/...> \
   --input samplesheet.csv \
   --outdir <OUTDIR>
```

Implementado en Nextflow DSL2 con un contenedor por proceso (Docker/Singularity) y módulos compartidos de [nf-core/modules](https://github.com/nf-core/modules).

**Puntos a considerar para GEMA MX**

- Los alelos HLA varían entre poblaciones, por lo que la tipificación en pacientes mexicanas sería un insumo relevante para cualquier análisis inmunológico o de neoantígenos.
- El repositorio actual usa las tablas MOESM8/9/4 del artículo Romero-Córdoba (variantes ya llamadas), no lecturas crudas. Integrar este pipeline requeriría acceso a FASTQ o BAM de la cohorte.
- Por estar en nf-core y en DSL2, es el más fácil de acoplar como subworkflow a `main_v2.nf`.

---

## 3. WiGiTS (hmftools) y Oncoanalyser

**Repositorio:** <https://github.com/hartwigmedical/hmftools> · **Implementación Nextflow:** <https://nf-co.re/oncoanalyser>

WiGiTS es una suite abierta de herramientas de análisis de genoma y transcriptoma para investigación y diagnóstico en cáncer, desarrollada por el Hartwig Medical Foundation. El repositorio indica como release actual la v3.0 del pipeline y recomienda ejecutarlo con **Oncoanalyser**, su implementación en Nextflow. Puede correrse también sobre paneles dirigidos (por ejemplo TSO500).

**Herramientas más relevantes para GEMA MX**

| Herramienta | Función |
|---|---|
| Sage | Llamado y filtrado de mutaciones puntuales |
| Pave | Anotación de mutaciones puntuales e impacto en el gen |
| Purple | Número de copias, pureza, ploidía y eventos driver |
| Lilac | Tipificación HLA |
| Neo | Neoepítopos |
| Linx | Anotación de variantes estructurales, fusiones y disrupciones |
| Isofox | Abundancia de transcritos, fusiones y empalmes nuevos (RNA) |
| Cuppa | Predicción del tejido de origen |
| Protect / Rose | Vinculación de hallazgos moleculares con tratamientos y ensayos clínicos, y evaluación de accionabilidad |
| Orange | Reporte resumen en PDF y JSON |

**Puntos a considerar para GEMA MX**

- Protect, Rose y Pave cubren un espacio cercano al de GEMA MX (priorización clínica de variantes y vínculo con fármacos), con otro enfoque: aquí se usa docking molecular, allá evidencia clínica curada.
- Lilac y Neo ofrecen una ruta alternativa a nf-core/hlatyping + NeoFlow dentro de un mismo ecosistema.
- La licencia es **GPL-3.0**, distinta de la licencia MIT de este proyecto. Ejecutar las herramientas como software externo es una cosa; incorporar su código al repositorio es otra y debe revisarse.
- Está pensado para datos crudos de WGS/WES/WTS, no para tablas MAF ya procesadas.

---

## Posibles líneas de integración

| Idea | Insumo necesario | Proyecto de referencia |
|---|---|---|
| Tipificar HLA en la cohorte mexicana | FASTQ/BAM de WES o RNA-seq | nf-core/hlatyping, Lilac |
| Predecir neoepítopos de las variantes priorizadas | Variantes + genotipo HLA | NeoFlow (módulo 4), Neo |
| Contrastar la priorización por frecuencia con evidencia clínica curada | Variantes anotadas | Protect, Rose, Pave |
| Adoptar buenas prácticas de nf-core (tests, esquema de parámetros, CI) | Ninguno | nf-core/hlatyping |

## Referencias

- Wen, B., Li, K., Zhang, Y. et al. (2020). *Cancer neoantigen prioritization through sensitive and reliable proteogenomics analysis*. Nature Communications 11, 1759. <https://doi.org/10.1038/s41467-020-15456-w>
- Ewels, P. A., et al. (2020). *The nf-core framework for community-curated bioinformatics pipelines*. Nature Biotechnology. <https://doi.org/10.1038/s41587-020-0439-x>
- nf-core/hlatyping: <https://doi.org/10.5281/zenodo.1401039>
- OptiType: <https://github.com/FRED-2/OptiType>
- Hartwig Medical Foundation, WiGiTS / hmftools: <https://github.com/hartwigmedical/hmftools>
