#!/usr/bin/env python3
"""INGEST — variantes de TCGA-BRCA (cBioPortal) -> raw_mutations.json + top_variants.json.

Dos modos:
  - `--mutations-json` : snapshot local (perfil `test`, sin red).
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

BASE_URL = "https://www.cbioportal.org/api"
CHUNK = 500


def http_json(method: str, url: str, payload=None, timeout: int = 120, retries: int = 4):
    """Petición HTTP con reintentos y backoff (red inestable)."""
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.request(method, url, json=payload, timeout=timeout)
            if response.status_code == 200:
                return response.json()
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            if response.status_code < 500:
                break
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(2 ** attempt)
    die(f"fallo consultando {url}: {last_error}")


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


def classify(cohort_pct: float) -> str:
    if cohort_pct >= 5.0:
        return "Patogénica"
    if cohort_pct >= 1.0:
        return "Probable Patogénica"
    if cohort_pct >= 0.5:
        return "VUS"
    return "Baja Frecuencia"


def build_ranking(rows: list[dict], genes: set[str], max_variants: int,
                  total_samples: int) -> list[dict]:
    missense = [
        r for r in rows
        if r["hugo_symbol"] in genes
        and "missense" in (r["variant_classification"] or "").lower()
        and r["protein_change"]
    ]
    if not missense:
        die("no hay variantes missense en los genes solicitados")

    counts = Counter((r["hugo_symbol"], r["protein_change"]) for r in missense)
    coords: dict[tuple[str, str], tuple[str, int]] = {}
    for r in missense:
        key = (r["hugo_symbol"], r["protein_change"])
        chrom, pos = coords.get(key, ("?", 0))
        if chrom in (None, "", "?") and r["chromosome"] not in (None, ""):
            chrom = str(r["chromosome"])
        if (pos in (None, 0)) and r["start_position"]:
            pos = int(r["start_position"])
        coords[key] = (chrom, pos)

    ranking = []
    for (gene, change), frequency in counts.items():
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingesta de variantes TCGA-BRCA")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--study", default="brca_tcga")
    parser.add_argument("--genes", required=True, help="símbolos HUGO separados por coma")
    parser.add_argument("--max-variants", type=int, default=20)
    parser.add_argument("--mutations-json", help="snapshot local (sin red)")
    parser.add_argument("--total-samples", type=int,
                        help="tamaño de cohorte (por defecto, muestras únicas de los datos)")
    args = parser.parse_args()

    genes = {g.strip().upper() for g in args.genes.split(",") if g.strip()}
    if not genes:
        die("--genes está vacío")

    if args.mutations_json:
        records = load_snapshot(args.mutations_json)
        rows = normalize(records, None)
        source = Path(args.mutations_json).name
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

    if not rows:
        die("la ingesta no devolvió mutaciones")
    if total_samples <= 0:
        die("no se pudo determinar el tamaño de la cohorte (usa --total-samples)")

    rows.sort(key=lambda r: (
        r["hugo_symbol"] or "", r["sample_id"] or "",
        r["protein_change"] or "", r["start_position"] or 0,
    ))

    ranking = build_ranking(rows, genes, args.max_variants, total_samples)

    outdir = Path(args.outdir)
    write_json(outdir / "raw_mutations.json", rows)
    write_json(outdir / "top_variants.json", ranking)

    print(f"OK ingesta: {len(rows)} mutaciones, cohorte {total_samples}, "
          f"{len(ranking)} variantes priorizadas ({source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
