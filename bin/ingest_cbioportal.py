#!/usr/bin/env python3
"""INGEST — variantes y clínica de TCGA-BRCA (cBioPortal o Contrato V3).

Salidas base:
  raw_mutations.json, top_variants.json (mutation_stats.json lo escribe
  build_stats.py a partir de raw_mutations.json).

Con `--clinical` (o `--clinical-json`) añade:
  clinical_metadata.json        perfil clínico por muestra
  variant_clinical_summary.json agregados variante x clínica

`RACE` y `ETHNICITY` son atributos **autorreportados a nivel paciente** en
cBioPortal: no son ancestría genética ni país de origen. La ancestría estimada
de TCGA no está en cBioPortal y no se ingiere aquí.

Tres modos:
  - `--contract-dir`   : bundle versionado del ETL (V3). Ingesta a nivel
                         paciente, sin red, con validación previa del contrato.
  - `--mutations-json` : snapshot local de mutaciones (perfil `test`, sin red).
  - sin él            : descarga desde la API de cBioPortal.

El ranking reproduce el contrato del legado: genes clave + missense, agrupado
por (gen, cambio), ordenado por frecuencia y clasificado por porcentaje de
cohorte. Se añade un desempate determinista (gen, cambio) que el legado no
tenía.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gemamx_common import die, read_json, write_json  # noqa: E402
from validate_contract import load_contract, validate_contract_dir  # noqa: E402

BASE_URL = "https://www.cbioportal.org/api"
CHUNK = 500

# Clínica opcional (--clinical / --clinical-json). RACE y ETHNICITY son
# autorreportados por el paciente: se documentan como tal en el contrato.
DEFAULT_CLINICAL_ATTRIBUTES = ("RACE", "ETHNICITY", "AGE")
NO_DATA_LABEL = "Sin dato"
CLINICAL_NOTE = ("RACE/ETHNICITY son datos autorreportados por el paciente "
                 "(TCGA); no son ancestría genética ni país de origen.")
MISSING_VALUES = {
    "", "NA", "N/A", "NAN", "NONE", "NULL", "UNKNOWN", "NOT REPORTED",
    "NOT AVAILABLE", "NOT APPLICABLE", "<NA>", "N.D.", "ND", "SIN DATO",
}
REQUEST_LOG: list[dict] = []


def http_json(method: str, url: str, payload=None, timeout: int = 120, retries: int = 4,
              required: bool = True):
    """Petición HTTP con reintentos y backoff (red inestable).

    Con `required=False` devuelve None en vez de abortar; se usa para enriquecer
    datos opcionales (p. ej. el mapa sampleId -> patientId) sin romper la corrida.
    """
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.request(method, url, json=payload, timeout=timeout)
            if response.status_code == 200:
                result = response.json()
                REQUEST_LOG.append({
                    "method": method,
                    "url": url,
                    "request": payload,
                    "response_records": len(result) if isinstance(result, list) else None,
                })
                return result
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            if response.status_code < 500:
                break
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(2 ** attempt)
    if required:
        die(f"fallo consultando {url}: {last_error}")
    return None


def sample_ids(study: str) -> list[str]:
    lists = http_json("GET", f"{BASE_URL}/studies/{study}/sample-lists")
    if not lists:
        die(f"el estudio {study} no tiene sample lists")
    chosen = next((sl["sampleListId"] for sl in lists if "all" in sl["sampleListId"]),
                  lists[0]["sampleListId"])
    return http_json("GET", f"{BASE_URL}/sample-lists/{chosen}/sample-ids")


def fetch_mutations(study: str, samples: list[str]) -> list[dict]:
    profile = f"{study}_mutations"
    url = f"{BASE_URL}/molecular-profiles/{profile}/mutations/fetch"
    records: list[dict] = []
    for index in range(0, len(samples), CHUNK):
        records.extend(http_json("POST", url, {"sampleIds": samples[index:index + CHUNK]}))
    return records


def gene_symbols(entrez_ids: list[int]) -> dict[int, str]:
    url = f"{BASE_URL}/genes/fetch"
    mapping: dict[int, str] = {}
    for index in range(0, len(entrez_ids), CHUNK):
        chunk = [int(x) for x in entrez_ids[index:index + CHUNK] if x]
        if not chunk:
            continue
        for gene in http_json("POST", url, chunk):
            mapping[gene["entrezGeneId"]] = gene["hugoGeneSymbol"]
    return mapping


def load_snapshot(path: str) -> list[dict]:
    data = read_json(path)
    if not isinstance(data, list):
        die(f"el snapshot debe ser una lista de mutaciones: {path}")
    return data


def normalize(records: list[dict], mapping: dict[int, str] | None) -> list[dict]:
    normalized = []
    for row in records:
        hugo = row.get("hugo_symbol")
        if not hugo and mapping:
            hugo = mapping.get(row.get("entrezGeneId"))
        item = {
            "hugo_symbol": hugo,
            "variant_classification": row.get("variant_classification", row.get("mutationType")),
            "protein_change": row.get("protein_change", row.get("proteinChange")),
            "sample_id": row.get("sample_id", row.get("sampleId")),
            "chromosome": row.get("chromosome", row.get("chr")),
            "start_position": row.get("start_position", row.get("startPosition")),
        }
        normalized.append(item)
    return normalized


def normalize_contract(records: list[dict], manifest: dict) -> list[dict]:
    """Normaliza el bundle 2.0.0 conservando paciente y variante.

    A diferencia de cBioPortal, el contrato ya trae una fila por
    `(patient_id, variant_id)` y la muestra tumoral resuelta. No se vuelve a
    agrupar por muestra para no perder la unidad paciente.
    """
    bundle_id = manifest.get("bundle_id")
    release = manifest.get("gdc_data_release")
    rows = []
    for row in records:
        rows.append({
            "variant_id": row.get("variant_id"),
            "patient_id": row.get("patient_id"),
            "sample_id": row.get("sample_id"),
            "sample_ids": row.get("sample_ids") or [],
            "hugo_symbol": row.get("hugo_symbol"),
            "variant_classification": row.get("variant_classification"),
            "protein_change": row.get("protein_change"),
            "chromosome": row.get("chromosome"),
            "start_position": row.get("start_position"),
            "end_position": row.get("end_position"),
            "reference_allele": row.get("reference_allele"),
            "tumor_seq_allele2": row.get("tumor_seq_allele2"),
            "genomic_dna_change": row.get("genomic_dna_change"),
            "mutation_status": row.get("mutation_status"),
            "filter_status": row.get("filter_status"),
            "t_depth": row.get("t_depth"),
            "t_ref_count": row.get("t_ref_count"),
            "t_alt_count": row.get("t_alt_count"),
            "hgvsc": row.get("hgvsc"),
            "hgvsp_short": row.get("hgvsp_short"),
            "transcript_id": row.get("transcript_id"),
            "file_id": row.get("file_id"),
            "n_samples": row.get("n_samples"),
            "gdc_data_release": row.get("gdc_data_release") or release,
            "bundle_id": bundle_id,
            "contract_version": manifest.get("contract_version"),
            "mutation_scope": manifest.get("mutation_scope"),
            "data_origin": manifest.get("data_origin"),
        })
    return rows


def contract_source(manifest: dict) -> str:
    """Etiqueta de procedencia que se propaga a los JSON y a la webapp."""
    return (
        f"Contrato {manifest.get('contract_version')} · "
        f"{manifest.get('bundle_id')} · "
        f"GDC {manifest.get('gdc_data_release')} · "
        f"alcance {manifest.get('mutation_scope')}"
    )


def build_contract_provenance(manifest: dict) -> dict:
    """Resumen de procedencia para webapp/MLflow (sin payloads clínicos)."""
    counts = manifest.get("counts") or {}
    cohort = manifest.get("cohort") or {}
    return {
        "contract_version": manifest.get("contract_version"),
        "bundle_id": manifest.get("bundle_id"),
        "dataset_id": manifest.get("dataset_id"),
        "project_id": manifest.get("project_id"),
        "gdc_data_release": manifest.get("gdc_data_release"),
        "gdc_api_tag": manifest.get("gdc_api_tag"),
        "mutation_scope": manifest.get("mutation_scope"),
        "data_origin": manifest.get("data_origin"),
        "curated": manifest.get("curated"),
        "cohort_total_cases": cohort.get("total_cases", counts.get("cohort_cases")),
        "cohort_cases_with_mutations": cohort.get("cases_with_mutations"),
        "mutation_records": counts.get("mutation_records"),
        "mutation_patients": counts.get("mutation_patients"),
        "clinical_records": counts.get("clinical_records"),
        "exported_at": manifest.get("exported_at"),
        "validation_passed": (manifest.get("validation") or {}).get("passed"),
    }


def classify(cohort_pct: float) -> str:
    if cohort_pct >= 5.0:
        return "Patogénica"
    if cohort_pct >= 1.0:
        return "Probable Patogénica"
    if cohort_pct >= 0.5:
        return "VUS"
    return "Baja Frecuencia"


def build_ranking(rows: list[dict], genes: set[str], max_variants: int,
                  total_samples: int, carrier_key: str = "sample_id") -> list[dict]:
    # Filtro, conteo y coordenadas en una sola pasada sobre las mutaciones.
    # `carrier_key` permite contar pacientes (contrato V3) o muestras (cBioPortal)
    # sin duplicar una variante presente en varias filas del mismo portador.
    carriers: dict[tuple[str, str], set[str]] = defaultdict(set)
    coords: dict[tuple[str, str], tuple[str, int]] = {}
    for r in rows:
        if not (r["hugo_symbol"] in genes
                and "missense" in (r["variant_classification"] or "").lower()
                and r["protein_change"]):
            continue
        key = (r["hugo_symbol"], r["protein_change"])
        carrier = r.get(carrier_key) or r.get("sample_id")
        if carrier:
            carriers[key].add(str(carrier))
        chrom, pos = coords.get(key, ("?", 0))
        if chrom in (None, "", "?") and r["chromosome"] not in (None, ""):
            chrom = str(r["chromosome"])
        if (pos in (None, 0)) and r["start_position"]:
            pos = int(r["start_position"])
        coords[key] = (chrom, pos)

    if not carriers:
        die("no hay variantes missense en los genes solicitados")

    ranking = []
    for (gene, change), carrier_set in carriers.items():
        frequency = len(carrier_set)
        chrom, pos = coords[(gene, change)]
        pct = frequency / total_samples * 100
        ranking.append({
            "hugo_symbol": gene,
            "protein_change": change,
            "chromosome": chrom,
            "start_position": pos,
            "frequency": frequency,
            "cohort_percentage": round(pct, 6),
            "classification": classify(pct),
        })

    ranking.sort(key=lambda r: (-r["frequency"], r["hugo_symbol"], r["protein_change"]))
    ranking = ranking[:max_variants]
    for index, row in enumerate(ranking, start=1):
        row["rank"] = index
    return ranking


# ---------------------------------------------------------------------------
# Clínica opcional (RACE, ETHNICITY, AGE y los atributos que se pidan)
# ---------------------------------------------------------------------------

def parse_attributes(spec: str) -> list[str]:
    """'race, ethnicity,AGE' -> ['RACE', 'ETHNICITY', 'AGE'] (sin duplicados)."""
    attributes = []
    for item in spec.split(","):
        item = item.strip().upper()
        if item and item not in attributes:
            attributes.append(item)
    return attributes


def clean_text(value) -> str | None:
    """Normaliza marcadores de vacío a None; conserva el resto como texto."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text.upper() in MISSING_VALUES else text


def normalize_label(value) -> str | None:
    """Etiqueta comparable entre estudios ('Not Hispanic Or Latino' -> mayúsculas)."""
    text = clean_text(value)
    return " ".join(text.upper().split()) if text else None


def parse_age(value) -> int | float | None:
    """Edad numérica razonable; cualquier otra cosa (o vacío) -> None."""
    text = clean_text(value)
    if text is None:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not 0 <= number <= 120:
        return None
    return int(number) if number.is_integer() else round(number, 1)


def load_clinical_snapshot(path: str) -> list[dict]:
    data = read_json(path)
    if not isinstance(data, list):
        die(f"el snapshot clínico debe ser una lista de registros: {path}")
    return data


def sequenced_sample_ids(study: str) -> list[str]:
    """Muestras con datos de secuenciación; si no hay lista, todas las del estudio."""
    lists = http_json("GET", f"{BASE_URL}/studies/{study}/sample-lists")
    if not lists:
        die(f"el estudio {study} no tiene sample lists")
    chosen = next((sl["sampleListId"] for sl in lists
                   if sl["sampleListId"].endswith("_sequenced")), None)
    if chosen is None:
        chosen = next((sl["sampleListId"] for sl in lists
                       if "all" in sl["sampleListId"]), lists[0]["sampleListId"])
    return http_json("GET", f"{BASE_URL}/sample-lists/{chosen}/sample-ids")


def sample_patient_map(study: str, samples: list[str]) -> dict[str, str]:
    """sampleId -> patientId. Usa /samples y cae al barcode de 12 caracteres."""
    mapping = {sample: sample[:12] for sample in samples}
    rows = http_json("GET", f"{BASE_URL}/studies/{study}/samples?projection=SUMMARY",
                     required=False)
    if rows:
        for row in rows:
            sample_id, patient_id = row.get("sampleId"), row.get("patientId")
            if sample_id in mapping and patient_id:
                mapping[sample_id] = patient_id
    return mapping


def snapshot_sample_patient_map(records: list[dict], samples: list[str]) -> dict[str, str]:
    """Igual que sample_patient_map, pero sin red: usa los patientId del snapshot."""
    mapping = {sample: sample[:12] for sample in samples}
    for row in records:
        sample_id, patient_id = row.get("sampleId"), row.get("patientId")
        if sample_id and patient_id:
            mapping[sample_id] = patient_id
    return mapping


def fetch_clinical(study: str, samples: list[str], attributes: list[str]) -> list[dict]:
    """Registros de clinical-data (nivel paciente) para los atributos pedidos."""
    available = http_json("GET", f"{BASE_URL}/studies/{study}/clinical-attributes")
    patient_attributes = {row.get("clinicalAttributeId") for row in available
                          if row.get("patientAttribute")}
    requested = [attribute for attribute in attributes
                 if attribute in patient_attributes]
    skipped = [attribute for attribute in attributes
               if attribute not in patient_attributes]
    if skipped:
        print(f"AVISO: atributos clínicos no disponibles en {study}: "
              f"{', '.join(skipped)}")
    if not requested:
        return []

    patients = sorted(set(sample_patient_map(study, samples).values()))
    url = f"{BASE_URL}/clinical-data/fetch?clinicalDataType=PATIENT"
    records: list[dict] = []
    for index in range(0, len(patients), CHUNK):
        identifiers = [{"entityId": patient, "studyId": study}
                       for patient in patients[index:index + CHUNK]]
        records.extend(http_json("POST", url,
                                 {"identifiers": identifiers,
                                  "attributeIds": requested}))
    return records


def build_clinical_metadata(samples: list[str], sample_to_patient: dict[str, str],
                            records: list[dict], attributes: list[str],
                            source: str) -> list[dict]:
    """Un registro por muestra, cruzando atributos de paciente y de muestra."""
    patient_attributes: dict[str, dict[str, str]] = defaultdict(dict)
    sample_attributes: dict[str, dict[str, str]] = defaultdict(dict)
    for row in records:
        attribute = row.get("clinicalAttributeId") or row.get("attributeId")
        if not attribute:
            continue
        attribute = str(attribute).upper()
        sample_id = row.get("sampleId") or None
        patient_id = row.get("patientId") or None
        if sample_id:
            sample_attributes[sample_id][attribute] = row.get("value")
        elif patient_id:
            patient_attributes[patient_id][attribute] = row.get("value")

    metadata = []
    for sample_id in samples:
        patient_id = sample_to_patient.get(sample_id)
        values = dict(patient_attributes.get(patient_id or "", {}))
        values.update(sample_attributes.get(sample_id, {}))
        race = normalize_label(values.get("RACE"))
        ethnicity = normalize_label(values.get("ETHNICITY"))
        histology = normalize_label(values.get("HISTOLOGY"))
        pam50 = normalize_label(values.get("SUBTYPE_PAM50") or values.get("PAM50"))
        metadata.append({
            "sample_id": sample_id,
            "patient_id": patient_id,
            "age": parse_age(values.get("AGE")),
            "race": race,
            "ethnicity": ethnicity,
            "histology": histology,
            "pam50": pam50,
            "race_source": "cBioPortal:RACE" if race else None,
            "ethnicity_source": "cBioPortal:ETHNICITY" if ethnicity else None,
            "histology_source": "GDC:HISTOLOGY" if histology else None,
            # La cohorte clínica se construye sobre muestras secuenciadas.
            "mutation_wes": "Yes",
            "missing_attributes": [attribute for attribute in attributes
                                   if normalize_label(values.get(attribute)) is None],
            # Valores crudos, sin normalizar, para auditoría.
            "attributes": {attribute: values.get(attribute)
                           for attribute in attributes},
            "clinical_source": source,
        })
    return metadata


def build_contract_clinical(cohort: list[dict], records: list[dict],
                            manifest: dict) -> list[dict]:
    """Un registro por paciente a partir de clinical_attributes.json.

    El contrato V3 une por `patient_id`, no por muestra. Se mantiene
    `sample_id = patient_id` para que la webapp trate al paciente como unidad
    de cohorte, y se expone `patient_id` de forma explícita.
    """
    by_patient: dict[str, dict[str, str | None]] = defaultdict(dict)
    attributes: set[str] = set()
    for row in records:
        patient = row.get("patientId")
        attribute = row.get("clinicalAttributeId")
        if not patient or not attribute:
            continue
        attribute = str(attribute).upper()
        attributes.add(attribute)
        by_patient[patient][attribute] = row.get("value")

    ordered_attributes = sorted(attributes)
    source = contract_source(manifest)
    provenance = {
        "contract_version": manifest.get("contract_version"),
        "bundle_id": manifest.get("bundle_id"),
        "gdc_data_release": manifest.get("gdc_data_release"),
        "mutation_scope": manifest.get("mutation_scope"),
        "data_origin": manifest.get("data_origin"),
    }

    metadata = []
    for case in cohort:
        patient = case.get("case_code")
        if not patient:
            continue
        values = by_patient.get(patient, {})
        race = normalize_label(values.get("RACE"))
        ethnicity = normalize_label(values.get("ETHNICITY"))
        histology = normalize_label(values.get("HISTOLOGY"))
        pam50 = normalize_label(values.get("SUBTYPE_PAM50") or values.get("PAM50"))
        metadata.append({
            "sample_id": patient,
            "patient_id": patient,
            "cohort_unit": "patient",
            "age": parse_age(values.get("AGE")),
            "race": race,
            "ethnicity": ethnicity,
            "histology": histology,
            "stage": normalize_label(values.get("STAGE")),
            "vital_status": normalize_label(values.get("VITAL_STATUS")),
            "primary_site": normalize_label(values.get("PRIMARY_SITE")),
            "pam50": pam50,
            "ihc_subtype": None,
            "race_source": "GDC:demographics" if race else None,
            "ethnicity_source": "GDC:demographics" if ethnicity else None,
            "histology_source": "GDC:diagnoses" if histology else None,
            "mutation_wes": "Yes",
            "missing_attributes": [attribute for attribute in ordered_attributes
                                   if normalize_label(values.get(attribute)) is None],
            "attributes": {attribute: values.get(attribute)
                           for attribute in ordered_attributes},
            "clinical_source": source,
            "clinical_data_note": CLINICAL_NOTE,
            **provenance,
        })
    return metadata


def _distribution(values) -> dict[str, int]:
    counts = Counter(values)
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def build_variant_clinical_summary(top: list[dict], rows: list[dict],
                                   clinical: list[dict], min_cell: int = 5,
                                   source: str = "cBioPortal") -> list[dict]:
    """Agregados variante x clínica; marca celdas con n < min_cell."""
    # El contrato V3 trae clínica por paciente; cBioPortal, por muestra. Se
    # indexa por ambas claves para no perder ninguna de las dos convenciones.
    clinical_by_key: dict[str, dict] = {}
    for row in clinical:
        for key in (row.get("patient_id"), row.get("sample_id")):
            if key and key not in clinical_by_key:
                clinical_by_key[key] = row

    carriers: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in rows:
        carrier = row.get("patient_id") or row.get("sample_id")
        gene = row.get("hugo_symbol")
        change = row.get("protein_change")
        if carrier and gene and change:
            carriers[(gene, change)].add(str(carrier))

    summary = []
    for variant in top:
        gene = variant.get("hugo_symbol")
        change = variant.get("protein_change")
        carrier_ids = sorted(carriers.get((gene, change), set()))
        matched = [clinical_by_key[carrier] for carrier in carrier_ids
                   if carrier in clinical_by_key]
        ages = [row["age"] for row in matched if row.get("age") is not None]
        ethnicity = _distribution(row.get("ethnicity") or NO_DATA_LABEL
                                  for row in matched)
        race = _distribution(row.get("race") or NO_DATA_LABEL for row in matched)
        small_cells = []
        for dimension, counts in (("ethnicity", ethnicity), ("race", race)):
            small_cells.extend(f"{dimension}:{label}"
                               for label, count in counts.items()
                               if count < min_cell)
        histology_dist = _distribution(row.get("histology") for row in matched if row.get("histology"))
        pam50_dist = _distribution(row.get("pam50") for row in matched if row.get("pam50"))
        top_hist = max(histology_dist.items(), key=lambda x: x[1])[0] if histology_dist else None
        top_p50 = max(pam50_dist.items(), key=lambda x: x[1])[0] if pam50_dist else None

        summary.append({
            "variant_id": f"{gene}_{change}",
            "hugo_symbol": gene,
            "protein_change": change,
            "sample_count": len(carrier_ids),
            "matched_clinical_count": len(matched),
            "age": ({
                "n": len(ages),
                "mean": round(sum(ages) / len(ages), 1),
                "min": min(ages),
                "max": max(ages),
            } if ages else None),
            "ethnicity_distribution": ethnicity,
            "race_distribution": race,
            "histology_distribution": histology_dist,
            "pam50_distribution": pam50_dist,
            "small_cells": sorted(small_cells),
            "small_cell_threshold": min_cell,
            "clinical_source": source,
            "clinical_data_note": CLINICAL_NOTE,
            "contract_version": next(
                (row.get("contract_version") for row in matched
                 if row.get("contract_version")), None),
            "bundle_id": next(
                (row.get("bundle_id") for row in matched if row.get("bundle_id")), None),
            "gdc_data_release": next(
                (row.get("gdc_data_release") for row in matched
                 if row.get("gdc_data_release")), None),
            "mutation_scope": next(
                (row.get("mutation_scope") for row in matched
                 if row.get("mutation_scope")), None),
            "data_origin": next(
                (row.get("data_origin") for row in matched
                 if row.get("data_origin")), None),
            "highlights": {
                "top_ihc_subtype": None,
                "top_pam50": top_p50,
                "top_histology": top_hist,
            },
        })
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingesta de variantes TCGA-BRCA")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--study", default="brca_tcga")
    parser.add_argument("--genes", required=True, help="símbolos HUGO separados por coma")
    parser.add_argument("--max-variants", type=int, default=20)
    parser.add_argument("--mutations-json", help="snapshot local (sin red)")
    parser.add_argument("--contract-dir",
                        help="bundle del Contrato V3 (sin red; ingesta por paciente)")
    parser.add_argument("--allow-curated", action="store_true",
                        help="permite bundles curados (solo smoke tests)")
    parser.add_argument("--total-samples", type=int,
                        help="tamaño de cohorte (por defecto, muestras únicas de los datos)")
    parser.add_argument("--clinical", action="store_true",
                        help="ingiere clínica de cBioPortal (RACE, ETHNICITY, AGE)")
    parser.add_argument("--clinical-json",
                        help="snapshot local de clinical data (sin red; implica --clinical)")
    parser.add_argument("--clinical-attributes",
                        default=",".join(DEFAULT_CLINICAL_ATTRIBUTES),
                        help="atributos clínicos separados por coma")
    parser.add_argument("--clinical-small-cell", type=int, default=5,
                        help="umbral para marcar celdas pequeñas (no las elimina)")
    args = parser.parse_args()
    REQUEST_LOG.clear()

    genes = {g.strip().upper() for g in args.genes.split(",") if g.strip()}
    if not genes:
        die("--genes está vacío")
    if args.clinical_small_cell < 1:
        die("--clinical-small-cell debe ser >= 1")

    contract = None
    contract_manifest: dict = {}
    if args.contract_dir:
        errors = validate_contract_dir(Path(args.contract_dir),
                                       allow_curated=args.allow_curated)
        if errors:
            die("contrato inválido en {}:\n  - {}".format(
                args.contract_dir, "\n  - ".join(errors)))
        contract = load_contract(Path(args.contract_dir))
        contract_manifest = contract["manifest"]
        rows = normalize_contract(contract["somatic_mutations.json"],
                                  contract_manifest)
        source = contract_source(contract_manifest)
        ingestion_mode = "etl_contract"
        query_filter = (contract_manifest.get("cohort") or {}).get("filter")
        cohort = contract_manifest.get("cohort") or {}
        counts = contract_manifest.get("counts") or {}
        total_samples = cohort.get("total_cases") or counts.get("cohort_cases")
        if not total_samples:
            die("el manifiesto del contrato no declara el tamaño de la cohorte")
        if args.total_samples and args.total_samples != total_samples:
            print(f"AVISO: --total-samples {args.total_samples} difiere del "
                  f"manifiesto ({total_samples}); se usa el manifiesto")
    elif args.mutations_json:
        records = load_snapshot(args.mutations_json)
        rows = normalize(records, None)
        source = Path(args.mutations_json).name
        ingestion_mode = "local_snapshot"
        query_filter = None
        if args.total_samples:
            total_samples = args.total_samples
        else:
            total_samples = len({r["sample_id"] for r in rows if r["sample_id"]})
    else:
        samples = sample_ids(args.study)
        records = fetch_mutations(args.study, samples)
        entrez = sorted({r.get("entrezGeneId") for r in records if r.get("entrezGeneId")})
        mapping = gene_symbols(entrez)
        rows = normalize(records, mapping)
        total_samples = len(samples)
        source = f"cBioPortal:{args.study}"
        ingestion_mode = "cbioportal_rest"
        query_filter = f"study={args.study}; sample-list selected by sampleListId containing 'all' (fallback first available)"

    if not rows:
        die("la ingesta no devolvió mutaciones")
    if total_samples <= 0:
        die("no se pudo determinar el tamaño de la cohorte (usa --total-samples)")

    rows.sort(key=lambda r: (
        r["hugo_symbol"] or "", r.get("patient_id") or r["sample_id"] or "",
        r["protein_change"] or "", r["start_position"] or 0,
    ))

    ranking = build_ranking(
        rows, genes, args.max_variants, total_samples,
        carrier_key="patient_id" if contract else "sample_id",
    )

    outdir = Path(args.outdir)
    write_json(outdir / "raw_mutations.json", rows, indent=None)
    write_json(outdir / "top_variants.json", ranking, indent=None)

    if contract is not None:
        metadata = build_contract_clinical(
            contract["cohort_cases.json"],
            contract["clinical_attributes.json"],
            contract_manifest,
        )
        clinical_source = contract_source(contract_manifest)
        summary = build_variant_clinical_summary(
            ranking, rows, metadata,
            min_cell=args.clinical_small_cell, source=clinical_source,
        )
        write_json(outdir / "clinical_metadata.json", metadata, indent=None)
        write_json(outdir / "variant_clinical_summary.json", summary, indent=None)
        write_json(outdir / "contract_provenance.json",
                   build_contract_provenance(contract_manifest), indent=2)
        print(f"OK clínico: {len(metadata)} pacientes, {len(summary)} variantes "
              f"({clinical_source})")
    elif args.clinical or args.clinical_json:
        attributes = parse_attributes(args.clinical_attributes)
        if not attributes:
            die("--clinical-attributes está vacío")

        if args.clinical_json:
            clinical_records = load_clinical_snapshot(args.clinical_json)
            clinical_source = (f"cBioPortal:{args.study} "
                               f"(snapshot {Path(args.clinical_json).name})")
            cohort_samples = sorted({r["sample_id"] for r in rows if r["sample_id"]})
            if not cohort_samples:
                cohort_samples = sorted({r["sampleId"] for r in clinical_records
                                         if r.get("sampleId")})
            sample_to_patient = snapshot_sample_patient_map(clinical_records,
                                                            cohort_samples)
        else:
            cohort_samples = sequenced_sample_ids(args.study)
            clinical_records = fetch_clinical(args.study, cohort_samples, attributes)
            sample_to_patient = sample_patient_map(args.study, cohort_samples)
            clinical_source = f"cBioPortal:{args.study}"

        if not cohort_samples:
            die("no hay muestras para construir clinical_metadata.json")
        metadata = build_clinical_metadata(cohort_samples, sample_to_patient,
                                           clinical_records, attributes,
                                           clinical_source)
        summary = build_variant_clinical_summary(ranking, rows, metadata,
                                                 min_cell=args.clinical_small_cell,
                                                 source=clinical_source)
        write_json(outdir / "clinical_metadata.json", metadata, indent=None)
        write_json(outdir / "variant_clinical_summary.json", summary, indent=None)
        print(f"OK clínico: {len(metadata)} muestras, {len(summary)} variantes "
              f"({clinical_source})")

    query = {
        "mode": ingestion_mode,
        "source": source,
        "cohort_filter": query_filter,
        "requests": REQUEST_LOG,
        "mutation_selection": {
            "genes": sorted(genes),
            "variant_classification_contains": "missense",
            "protein_change_required": True,
            "max_variants": args.max_variants,
            "carrier_unit": "patient" if contract else "sample",
        },
    }
    if contract is not None:
        query["bundle"] = {
            "bundle_id": contract_manifest.get("bundle_id"),
            "gdc_data_release": contract_manifest.get("gdc_data_release"),
            "mutation_scope": contract_manifest.get("mutation_scope"),
            "data_origin": contract_manifest.get("data_origin"),
            "files": contract_manifest.get("files", {}),
        }
    elif args.mutations_json:
        query["input_file"] = Path(args.mutations_json).name
    write_json(outdir / "data_ingest.json", {
        "schema_version": 1,
        "pipeline": args.study,
        "mode": ingestion_mode,
        "query": query,
        "counts": {
            "raw_mutation_records": len(rows),
            "cohort_units": total_samples,
            "prioritized_variants": len(ranking),
            "clinical_records": len(metadata) if (contract is not None or args.clinical or args.clinical_json) else 0,
        },
    }, sort_keys=True)

    print(f"OK ingesta: {len(rows)} mutaciones, cohorte {total_samples}, "
          f"{len(ranking)} variantes priorizadas ({source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
