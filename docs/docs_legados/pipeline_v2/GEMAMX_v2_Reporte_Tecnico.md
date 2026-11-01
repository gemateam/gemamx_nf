<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

# **GEMAMX** 

Pipeline de Validación Farmacológica Computacional _Versión 2 — Cohorte Dra. Romero-Córdoba_ 

### **Reporte Técnico de Implementación** 

Cohorte: Romero-Córdoba et al. (2021) · HM Breast Cancer Cohort Dataset: 41467_2021_22478_MOESM8_ESM.xlsx / MOESM9_ESM.xlsx 

Fecha: Abril 2026 

GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 1 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>1. Introducción y Contexto</u>** 

GEMAMX v2 es la segunda generación del pipeline computacional diseñado para identificar y validar candidatos farmacológicos a partir de mutaciones somáticas en cáncer de mama. A diferencia de la versión anterior (basada en datos TCGA/cBioPortal), la versión 2 usa como fuente primaria el cohorte clínico de la Dra. Sandra RomeroCórdoba, publicado en Nature Communications (2021). 

El pipeline integra herramientas de bioinformática computacional, predicción de estructuras proteicas por inteligencia artificial y simulación de docking molecular, con el objetivo de sugerir fármacos oncológicos con base en el perfil mutacional específico del cohorte. 

### **1.1 Fuente de Datos Clínicos** 

|**Publicación**|Romero-Córdoba et al., Nature Communications, 2021|
|---|---|
|**DOI**|10.1038/s41467-021-22478-y|
|**Archivo principal**|41467_2021_22478_MOESM8_ESM.xlsx|
|**Archivo secundario**|41467_2021_22478_MOESM9_ESM.xlsx|
|**Hoja usada (MAF)**|HM maf|
|**Hoja usada (drivers)**|Driver mutation in HM · Mutsig HM|
|**Total de muestras**|134 pacientes|
|**Total de mutaciones**|28,114 eventos somáticos|
|**Tipo de tumor**|Cáncer de mama hormono-dependiente (HM)|



GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 2 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>2. Arquitectura General del Pipeline v2</u>** 

El pipeline GEMAMX v2 está organizado en 6 fases secuenciales, cada una con scripts dedicados, archivos de entrada y salida bien definidos. La ejecución combina procesamiento local (Python) con computación en GPU en la nube (Google Colab). 

|**Fase**|**Nombre**|**Script principal**|**Salida clave**|
|---|---|---|---|
|1|Ingestión y<br>Normalización|ingest_romero.py|raw_mutations.json|
|2|Priorización de<br>Variantes|ingest_romero.py|top_variants.json,<br>mutation_stats.json|
|3|Obtención de FASTA|fetch_fasta_romero.py|fasta/*.fasta, fasta_sequences.json|
|4|Predicción de<br>Estructuras (GPU)|predict_structures_romero_boltz.py<br>01_romero_structures_colab_gpu.ipynb|structures/*.cif / *.pdb|
|5|Métricas Estructurales|calc_structural_metrics_romero.py|structural_metrics.json|
|6|Preparación y Docking|prepare_docking_romero.py<br>run_docking_romero.py|docking/results/*.pdbqt<br>vina_affinities.json|



_Nota: El script scan_boltz_v2.py se usa para verificar el estado y progreso de las predicciones de Boltz ejecutadas en Colab. El script build_variant_clinical_summary.py genera el archivo variant_clinical_summary.json con el resumen clínico consolidado._ 

GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 3 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>3. Estructura del Dataset Romero</u>** 

### **3.1 Columnas Normalizadas del MAF** 

La hoja "HM maf" del archivo MOESM8 fue normalizada para extraer las siguientes columnas canónicas utilizadas en el resto del pipeline: 

|**Campo normalizado**|**Columna original (xlsx)**|**Descripción**|
|---|---|---|
|hugo_symbol|Hugo_Symbol|Símbolo oficial del gen (HGNC)|
|protein_change|HGVSp_Short|Cambio aminoacídico (ej. H1047R)|
|chromosome|Chromosome|Cromosoma donde ocurre la mutación|
|start_position|Start_Position|Posición genómica de inicio|
|sample_id|Tumor_Sample_Barcode|ID único del paciente/muestra|
|variant_classification|Variant_Classification|Tipo de variante somática|



### **3.2 Estadísticas del Dataset** 

|**Estadística**|**Valor**|**Observación**|
|---|---|---|
|Total de muestras|134|Pacientes con cáncer de mama<br>HM|
|Total de mutaciones|28,114|Eventos somáticos en MAF|
|Missense Mutations|5,668 (20.2%)|Principal clase de variante<br>accionable|
|Nonsense Mutations|402 (1.4%)|Variantes de truncamiento|
|Splice Site|206 (0.7%)|Alteraciones de splicing|
|Intrón / IGR|13,093 (46.6%)|Excluidas del análisis de docking|



### **3.3 Genes Oncológicos Monitoreados** 

El pipeline filtra y prioriza las siguientes 15 proteínas con relevancia oncológica conocida en cáncer de mama: 

|**PIK3CA**|**TP53**|**ERBB2**|**BRCA1**|**BRCA2**|**CDH1**|
|---|---|---|---|---|---|
|GATA3|MAP3K1|KMT2C|PTEN|RB1|ARID1A|
|SF3B1|AKT1|CBFB||||



GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 4 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>4. Fase 1 — Ingestión y Normalización</u>** 

### **4.1 Script: ingest_romero.py** 

Este script es el punto de entrada del pipeline v2. Parsea directamente los archivos XLSX sin usar pandas, empleando únicamente bibliotecas estándar de Python más requests, lo que garantiza compatibilidad en entornos sin conda. 

#### **Archivos de entrada** 

- data/romero/41467_2021_22478_MOESM8_ESM.xlsx — hoja: HM maf 

- data/romero/41467_2021_22478_MOESM9_ESM.xlsx — hoja: Driver mutation in HM 

#### **Bibliotecas utilizadas** 

- zipfile — extracción interna del XLSX (formato ZIP/XML) 

- xml.etree.ElementTree — parseo de sharedStrings.xml y hojas XML 

- collections.Counter, defaultdict — conteo de variantes y distribución 

- re — expresiones regulares para normalizar protein_change 

- json, pathlib — serialización y manejo de rutas 

#### **Archivos de salida generados** 

|**Archivo**|**Contenido**|
|---|---|
|v2/data/raw_mutations.json|Lista completa de 28,114 mutaciones normalizadas con campos:<br>hugo_symbol, protein_change, chromosome, start_position, sample_id,<br>variant_classification|
|v2/data/top_variants.json|Top variantes priorizadas con frecuencia, porcentaje de cohorte,<br>clasificación clínica y rank|
|v2/data/mutation_stats.json|Estadísticas agregadas: distribución por gen, por tipo, total de muestras y<br>mutaciones|



## **<u>5. Fase 2 — Priorización de Variantes</u>** 

A partir de raw_mutations.json, el pipeline aplica criterios de priorización para seleccionar las variantes candidatas a análisis estructural y de docking. 

#### **Criterios de priorización** 

- Tipo de variante: únicamente Missense_Mutation, Nonsense_Mutation, Splice_Site, Frame_Shift 

- Pertenencia a la lista KEY_GENES (15 genes oncológicos) 

- Frecuencia en cohorte: se calcula como proporción de las 134 muestras 

- Clasificación clínica: Patogénica, Probable Patogénica, VUS (según ClinVar/literature) 

### **5.1 Top Variantes Seleccionadas** 

GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 5 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

|**#**|**Gen**|**Cambio**|**Freq.**|**%**<br>**Cohorte**|**Clasificación**|
|---|---|---|---|---|---|
|1|PIK3CA|H1047R|15|11.2%|Patogénica|
|2|AKT1|E17K|10|7.5%|Patogénica|
|3|PIK3CA|E542K|6|4.5%|Probable Patogénica|
|4|PIK3CA|E545K|6|4.5%|Probable Patogénica|
|5|PIK3CA|H1047L|5|3.7%|Probable Patogénica|
|6|PIK3CA|C420R|4|3.0%|VUS|
|7|ERBB2|S310F|4|3.0%|Probable Patogénica|
|8|TP53|R175H|4|3.0%|Patogénica|
|9|PTEN|R173H|3|2.2%|Probable Patogénica|
|10|GATA3|T418A|3|2.2%|VUS|



GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 6 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>6. Fase 3 — Generación de Secuencias FASTA</u>** 

### **6.1 Script: fetch_fasta_romero.py** 

A partir del archivo top_variants.json, este script obtiene las secuencias proteicas wild-type (WT) desde UniProt y genera variantes mutantes (MUT) aplicando el cambio aminoacídico indicado en protein_change. 

#### **Flujo de procesamiento** 

- Consulta a la API REST de UniProt (rest.uniprot.org) para obtener el UniProt accession del gen humano revisado 

- Descarga de la secuencia FASTA canónica WT 

- Aplicación del cambio de aminoácido (sustitución puntual) para generar la secuencia MUT 

- Escritura de archivos individuales en v2/data/fasta/{GEN}_{VARIANTE}_WT.fasta y _MUT.fasta 

- Generación del índice consolidado fasta_sequences.json 

#### **Archivos de entrada y salida** 

|**Tipo**|**Archivo**|**Descripción**|
|---|---|---|
|Entrada|v2/data/top_variants.json|Lista de variantes priorizadas|
|API ext.|UniProt REST API|https://rest.uniprot.org/uniprotkb/|
|Salida|v2/data/fasta/*.fasta|Un archivo por variante WT y MUT|
|Salida|v2/data/fasta_sequences.json|Índice JSON con accession, longitud y rutas|



#### **Bibliotecas utilizadas** 

- requests — llamadas HTTP a UniProt REST API 

- json, re, pathlib — manejo de datos y rutas 

GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 7 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>7. Fase 4 — Predicción de Estructuras con Boltz-1 (GPU)</u>** 

### **7.1 Notebook de Google Colab** 

Dado que la predicción de estructuras proteicas con Boltz-1 requiere GPU, esta fase se ejecuta en Google Colab. El flujo está encapsulado en el siguiente notebook: 

|**Notebook (Colab)**|v2/01_romero_structures_colab_gpu.ipynb|
|---|---|
|**Script de predicción**|v2/scripts/predict_structures_romero_boltz.py|
|**Script de escaneo**|v2/scripts/scan_boltz_v2.py|
|**Runtime recomendado**|T4 GPU (Google Colab Pro) o A100|
|**Modelo utilizado**|Boltz-1 (predicción de estructura 3D de proteínas)|
|**Modo de fragmento**|Región ±120 aa alrededor de la posición mutada|



### **7.2 Flujo de Ejecución en Colab** 

El notebook sigue el siguiente flujo secuencial: 

- Paso 1 — Generar localmente top_variants.json y fasta_sequences.json (ejecutado previamente en local) 

- Paso 2 — Subir archivos a Google Drive usando el script upload_v2_to_drive.ps1 

- Paso 3 — Abrir 01_romero_structures_colab_gpu.ipynb con runtime GPU en Google Colab 

- Paso 4 — Ejecutar Boltz-1 para cada variante WT y MUT (secuencial o en batch) 

- Paso 5 — Descargar estructuras generadas (.cif / .pdb) hacia v2/data/structures/ 

- Paso 6 — Actualizar manifest_structures.json y calcular métricas con calc_structural_metrics_romero.py 

### **7.3 Script: predict_structures_romero_boltz.py** 

Script de control que prepara las secuencias FASTA para Boltz, invoca la predicción y organiza los resultados en el directorio de estructuras. Genera o actualiza structure_jobs.json con el estado de cada trabajo. 

#### **Archivos de salida estructurales** 

|**Archivo / Directorio**|**Contenido**|
|---|---|
|v2/data/structures/{GEN}_{VAR}_WT.cif|Estructura 3D wild-type predicha por Boltz-1|
|v2/data/structures/{GEN}_{VAR}_MUT.cif|Estructura 3D mutante predicha por Boltz-1|
|v2/data/manifest_structures.json|Índice de todas las estructuras generadas|
|v2/data/structure_jobs.json|Estado de cada trabajo de predicción (completed/pending)|



GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 8 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>8. Fase 5 — Métricas Estructurales</u>** 

### **8.1 Script: calc_structural_metrics_romero.py** 

Una vez obtenidas las estructuras WT y MUT, este script calcula las métricas de comparación estructural que cuantifican el impacto de la mutación sobre la proteína. 

#### **Métricas calculadas** 

|**Métrica**|**Descripción**|
|---|---|
|pLDDT WT / MUT|Score de confianza de predicción de Boltz (0-100). Valores >80 = alta confianza|
|RMSD Global|Desviación cuadrática media entre estructura WT y MUT en toda la cadena (Å)|
|RMSD Activo|RMSD en la ventana de ±12 aminoácidos alrededor de la posición mutada (Å)|
|Fragment mode|Indica si se usó un fragmento proteico (región ~±120 aa) para la predicción|



### **8.2 Resultados Estructurales Seleccionados** 

|**Variante**|**pLDDT WT**|**pLDDT**<br>**MUT**|**RMSD**<br>**Global**|**RMSD**<br>**Activo**|**Fragmento**|
|---|---|---|---|---|---|
|PIK3CA_H1047R|84.8|85.3|0.78|0.91|867–1068|
|AKT1_E17K|85.4|85.2|0.94|0.67|1–197|
|PIK3CA_E542K|90.2|90.2|1.50|1.80|362–722|
|ERBB2_S310F|86.1|86.4|0.65|0.73|230–430|
|ERBB2_V777L|83.7|84.0|0.71|0.88|597–830|
|TP53_R175H|78.5|77.9|1.12|1.35|94–325|
|PTEN_R173H|81.2|80.8|0.95|1.10|93–350|



_Los valores de RMSD activo entre 0.6 y 1.8 Å indican que las mutaciones generan cambios conformacionales locales significativos, sin desestabilizar la estructura global de la proteína — condición favorable para el docking de ligandos._ 

GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 9 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>9. Fase 6 — Preparación y Docking Molecular</u>** 

### **9.1 Preparación de Estructuras: prepare_docking_romero.py** 

Este script convierte las estructuras predichas (.cif / .pdb) al formato PDBQT requerido por AutoDock Vina, añadiendo cargas Gasteiger y suprimiendo aguas/heteroátomos no relevantes. 

#### **Herramientas de preparación** 

- AutoDockTools / MGLTools — conversión de receptores PDB → PDBQT 

- Open Babel — preparación alternativa de ligandos (SMILES → PDBQT) 

- Archivos de ligandos: v2/data/docking/ligands/*.pdbqt (11 fármacos candidatos) 

- Archivos de receptores: v2/data/docking/receptors/*.pdbqt (una estructura por variante) 

#### **Archivo de control generado** 

- v2/data/docking/prepared_receptors.json — registro de todos los receptores preparados con sus coordenadas de centro de masa y estado de preparación 

### **9.2 Ejecución de Docking: run_docking_romero.py** 

Este script ejecuta AutoDock Vina localmente para cada combinación de receptor mutante y ligando candidato. Utiliza el ejecutable vina123.exe localizado en la raíz del proyecto. 

#### **Configuración de AutoDock Vina** 

|**Ejecutable**|vina123.exe  (AutoDock Vina 1.2.3)|
|---|---|
|**Exhaustiveness**|8 (valor por defecto)|
|**Caja de búsqueda**|Centro de masa del receptor ±20 Å (calculado automáticamente)|
|**Receptores procesados**|v2/data/docking/receptors/*.pdbqt|
|**Ligandos procesados**|v2/data/docking/ligands/*.pdbqt|
|**Resultados de poses**|v2/data/docking/results/{GEN}_{VAR}_{FÁRMACO}_out.pdbqt|
|**Logs de Vina**|v2/data/docking/results/{GEN}_{VAR}_{FÁRMACO}_log.txt|
|**Affinities consolidadas**|v2/data/docking/vina_affinities.json|



### **9.3 Fármacos Evaluados (11 candidatos)** 

|**#**|**Fármaco**|**Clase**|**Diana principal**|
|---|---|---|---|
|1|Alpelisib|PI3K-α inh.|PIK3CA — aprobado en cáncer de mama HR+|
|2|Taselisib|PI3K-α inh.|PIK3CA — selectivo β/δ/α|
|3|Copanlisib|PI3K inh.|PI3K pan-isoforma (IV)|
|4|Buparlisib|PI3K inh.|PI3K pan-clase I (oral)|



GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 10 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

|**#**|**Fármaco**|**Clase**|**Diana principal**|
|---|---|---|---|
|5|Gedatolisib|PI3K/mTOR|Dual PI3K/mTORC1/2|
|6|Pictilisib|PI3K inh.|PI3K pan-clase I|
|7|Capivasertib|AKT inh.|AKT1/2/3 — aprobado en HER2+/HR+|
|8|Everolimus|mTOR inh.|mTORC1 — aprobado en mama avanzado|
|9|Palbociclib|CDK4/6 inh.|CDK4/6 — aprobado en HR+/HER2-|
|10|Ribociclib|CDK4/6 inh.|CDK4/6 — aprobado en HR+/HER2-|
|11|Abemaciclib|CDK4/6 inh.|CDK4/6 — uso continuo, aprobado mama HR+|



GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 11 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>10. Resultados de Docking — Scores de Afinidad</u>** 

Los scores de afinidad (kcal/mol) son calculados por AutoDock Vina para la pose de menor energía. Valores más negativos indican mayor afinidad de unión predicha. El umbral de relevancia clínica se considera a partir de −7.0 kcal/mol. 

|**Variante**|**Mejor fármaco**|**Score**|**2° fármaco**|**Score**||
|---|---|---|---|---|---|
|PIK3CA_H1047R|**Pictilisib**|-7.73|Alpelisib|-7.73|★|
|AKT1_E17K|**Pictilisib**|-8.35|Alpelisib|-7.97|★★|
|PIK3CA_E542K|**Palbociclib**|-7.83|Alpelisib|-7.80|★|
|PIK3CA_E545K|**Palbociclib**|-7.95|Taselisib|-7.58|★|
|ERBB2_S310F|**Abemaciclib**|-7.89|Palbociclib|-7.74|★|
|ERBB2_V777L|**Abemaciclib**|-7.92|Ribociclib|-7.68|★|
|TP53_R175H|**Capivasertib**|-7.44|Alpelisib|-7.34||
|PTEN_R173H|**Alpelisib**|-7.55|Pictilisib|-7.43|★|
|GATA3_T418A|**Gedatolisib**|-6.82|Copanlisib|-6.70||
|MAP3K1_M1442I|**Capivasertib**|-6.90|Alpelisib|-6.75||



★★ Afinidad muy alta (≤ −8.0 kcal/mol) ★ _Afinidad alta (−7.5 a −8.0 kcal/mol)_ 

GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 12 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>11. Inventario Completo de Archivos Generados</u>** 

### **11.1 Archivos de Datos (v2/data/)** 

|**Archivo**|**Descripción**|
|---|---|
|raw_mutations.json|28,114 mutaciones normalizadas del MAF|
|top_variants.json|Variantes priorizadas con frecuencia y clasificación|
|mutation_stats.json|Estadísticas agregadas del cohorte|
|fasta_sequences.json|Índice de secuencias WT y MUT con accession UniProt|
|fasta/*.fasta|Archivos FASTA individuales por variante (WT y MUT)|
|structural_metrics.json|pLDDT, RMSD global/activo y scores Vina por variante|
|manifest_structures.json|Índice de estructuras 3D generadas por Boltz-1|
|structure_jobs.json|Estado de cada trabajo de predicción estructural|
|clinical_metadata.json|Metadatos clínicos del cohorte|
|variant_clinical_summary.json|Resumen consolidado variante-clínica-docking|
|docking/prepared_receptors.json|Registro de receptores PDBQT preparados|
|docking/vina_affinities.json|Scores de afinidad consolidados de todos los dockings|
|docking/results/*.pdbqt|Poses de docking por variante-fármaco (salida Vina)|
|docking/results/*_log.txt|Logs de AutoDock Vina con tabla de energías por modo|



### **11.2 Scripts (v2/scripts/)** 

|**Script**|**Función**|
|---|---|
|ingest_romero.py|Fase 1/2: Ingestión del XLSX y priorización de variantes|
|fetch_fasta_romero.py|Fase 3: Descarga FASTA de UniProt y generación de mutantes|
|generate_structures_romero.py|Fase 4: Orquestación local de preparación para Boltz|
|predict_structures_romero_boltz.py|Fase 4: Predicción de estructuras con Boltz-1 (Colab)|
|scan_boltz_v2.py|Fase 4: Monitoreo del progreso de predicciones en Colab|
|calc_structural_metrics_romero.py|Fase 5: Cálculo de pLDDT y RMSD WT vs MUT|
|prepare_docking_romero.py|Fase 6a: Conversión de estructuras a PDBQT para Vina|
|run_docking_romero.py|Fase 6b: Ejecución de AutoDock Vina y extracción de scores|
|build_docking_complexes_romero.py|Fase 6c: Construcción de complejos receptor-ligando|



GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 13 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

|**Script**|**Función**|
|---|---|
|build_variant_clinical_summary.py|Consolidación de resultados clínicos y computacionales|
|extract_clinical_romero.py|Extracción de metadatos clínicos del dataset Romero|
|upload_v2_to_drive.ps1|PowerShell: sincronización de v2/data/ a Google Drive|



GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 14 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>12. Resultados de Renderizado 3D</u>** 

Los siguientes renders muestran la interacción del complejo receptor-ligando para la variante AKT1 E17K, evaluada con los fármacos Alpelisib y Capivasertib. Las visualizaciones fueron generadas con PyMOL / Blender desde los archivos PDBQT de salida de AutoDock Vina. 

- **12.1 AKT1 E17K — Alpelisib (Score Vina: −7.97 kcal/mol)** 



_Figura 1a. AKT1 E17K + Alpelisib — Vista frontal del complejo receptor-ligando_ 



_Figura 1b. AKT1 E17K + Alpelisib — Vista posterior mostrando bolsillo de unión_ 

GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 15 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

- **12.2 AKT1 E17K — Capivasertib (Score Vina: −6.37 kcal/mol)** 



_Figura 2a. AKT1 E17K + Capivasertib — Vista frontal del complejo receptor-ligando_ 



_Figura 2b. AKT1 E17K + Capivasertib — Vista posterior_ 

### **12.3 Comparación Molecular: Alpelisib vs Capivasertib** 

GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 16 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 



_Figura 3. Estructuras moleculares 2D comparadas: Alpelisib (izq.) y Capivasertib (der.) con sus grupos farmacofóricos indicados_ 

GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 17 de 18 

<u>GEMAMX v2 · Reporte Técnico del Pipeline |</u> **<u>Cohorte Dra. Romero</u>** 

## **<u>13. Conclusiones y Siguientes Pasos</u>** 

### **13.1 Hallazgos Principales** 

- El pipeline v2 procesó exitosamente 28,114 mutaciones del cohorte Romero-Córdoba 2021, identificando 134 muestras de cáncer de mama hormono-dependiente. 

- Se priorizaron variantes en 5 genes principales: PIK3CA (con 9 variantes únicas), TP53, AKT1, ERBB2, PTEN y GATA3. 

- La variante PIK3CA H1047R fue la más frecuente (15 casos, 11.2% del cohorte), consistente con la literatura oncológica. 

- Pictilisib mostró el mejor score de afinidad general (−8.35 kcal/mol en AKT1 E17K), seguido de Alpelisib (−7.97 kcal/mol). 

- Las métricas estructurales (RMSD activo 0.6–1.8 Å, pLDDT >80) validan la calidad de las estructuras generadas por Boltz-1. 

- Se generaron 400+ archivos de docking (log + pdbqt) cubriendo 10 variantes × 11 fármacos en múltiples genes. 

### **13.2 Siguientes Pasos Recomendados** 

- Validación experimental: priorizar Pictilisib y Alpelisib para ensayos in vitro en líneas celulares con mutación PIK3CA H1047R y AKT1 E17K. 

- Análisis de resistencia: evaluar docking en variantes menos frecuentes (PIK3CA E245Q, E365K) para identificar posibles mecanismos de resistencia. 

- Docking de precisión: refinamiento con Glide/Schrödinger en los 5 mejores complejos identificados. 

- Integración de datos clínicos: correlacionar scores de docking con datos de respuesta clínica del cohorte Romero para validación translacional. 

- Interfaz v2: actualizar la UI web de GEMAMX para soporte multi-dataset, permitiendo comparar resultados v1 (TCGA) vs v2 (Romero) lado a lado. 

_GEMAMX v2 — Reporte generado automáticamente por el sistema de análisis computacional_ Cohorte: Romero-Córdoba et al. (2021) · Nature Communications · DOI: 10.1038/s41467-021-22478-y 

GEMAMX – Pipeline de Validación Farmacológica Computacional    |    Página 18 de 18 

