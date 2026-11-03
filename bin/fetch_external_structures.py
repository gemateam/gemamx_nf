#!/usr/bin/env python3
"""fetch_external_structures.py — modelos AlphaFold DB para genes sin estructura propia.

El pipeline solo pliega (ESMFold) las variantes que llegan hasta STRUCTURE. Los
demás genes del Explorador (p. ej. ERBB4) no tienen estructura 3D y el visor
muestra «No hay estructura 3D publicada para esta variante». Este script
descarga el modelo WT de AlphaFold DB (secuencia completa de UniProt) y deja:

    structures/external/<GEN>_AF.cif     modelo mmCIF
    structures/external/index.json       gen -> {file, uniprot, plddt, ...}

La webapp lee ese índice (volumen `external/` de docker-compose) y lo usa solo
cuando el contrato de la corrida no trae estructura para el gen. Es independiente
de la corrida: no toca results/ ni se pierde al relanzar el pipeline.

Uso (solo biblioteca estándar, requiere red):
    python3 bin/fetch_external_structures.py --genes ERBB4
    python3 bin/fetch_external_structures.py --genes ERBB4,EGFR --uniprot EGFR=P00533
    python3 bin/fetch_external_structures.py --from-data results/data   # todos los genes sin estructura
    python3 bin/fetch_external_structures.py --genes ERBB4 --force      # re-descargar

Los accesos UniProt se resuelven con la API de UniProt (humano, revisado);
--uniprot GEN=ACC los fija a mano.
"""
import argparse
import collections
import datetime
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AF_API = "https://alphafold.ebi.ac.uk/api/prediction/{acc}"
UNIPROT_SEARCH = "https://rest.uniprot.org/uniprotkb/search"
HEADERS = {"User-Agent": "gemamx-nf/1.0 (external structure fetch)", "Accept": "*/*"}


def http_get(url, timeout=60, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = exc
            if exc.code in (400, 403, 404):   # no tiene sentido reintentar
                break
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url} -> {last}")


def lookup_uniprot(gene):
    query = f"gene_exact:{gene} AND organism_id:9606 AND reviewed:true"
    url = UNIPROT_SEARCH + "?" + urllib.parse.urlencode(
        {"query": query, "fields": "accession", "format": "tsv", "size": 1})
    lines = http_get(url).decode("utf-8").strip().splitlines()
    return lines[1].strip() if len(lines) > 1 else None


def genes_without_structure(data_dir, top=None):
    """Genes de raw_mutations.json sin estructura en el manifest, del más al menos mutado."""
    manifest = json.loads((data_dir / "manifest_structures.json").read_text(encoding="utf-8"))
    raw = json.loads((data_dir / "raw_mutations.json").read_text(encoding="utf-8"))
    covered = set()
    for key in manifest:
        key = key[4:] if key.startswith("WT__") else key
        covered.add(key.split("_")[0])
    counts = collections.Counter(
        m.get("hugo_symbol") for m in raw
        if m.get("hugo_symbol") and m.get("hugo_symbol") != "Unknown")
    genes = [g for g, _ in counts.most_common() if g not in covered]
    return genes[:top] if top else genes


def fetch_gene(gene, acc, out_dir, force):
    meta = json.loads(http_get(AF_API.format(acc=acc)).decode("utf-8"))
    entry = meta[0] if isinstance(meta, list) and meta else meta
    cif_url = entry.get("cifUrl") if isinstance(entry, dict) else None
    if not cif_url:
        raise RuntimeError(f"AlphaFold DB no devolvió cifUrl para {acc}")

    dest = out_dir / f"{gene}_AF.cif"
    if force or not dest.is_file() or dest.stat().st_size == 0:
        data = http_get(cif_url, timeout=180)
        if not data.lstrip().startswith(b"data_"):
            raise RuntimeError(f"el archivo descargado de {cif_url} no parece mmCIF")
        dest.write_bytes(data)
        print(f"  ✓ {gene}: {dest.name} ({dest.stat().st_size / 1024:.0f} KB)")
    else:
        print(f"  = {gene}: {dest.name} ya existe (usa --force para re-descargar)")

    return {
        "file": dest.name,
        "uniprot": acc,
        "source": "AlphaFold DB",
        "version": entry.get("latestVersion"),
        "plddt": entry.get("globalMetricValue"),
        "model_url": cif_url,
        "fetched": datetime.date.today().isoformat(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--genes", help="símbolos HGNC separados por coma (p. ej. ERBB4,EGFR)")
    ap.add_argument("--from-data", type=Path,
                    help="directorio de datos de una corrida: usa los genes de raw_mutations.json "
                         "que no tienen estructura en manifest_structures.json")
    ap.add_argument("--top", type=int, metavar="N",
                    help="con --from-data, solo los N genes más mutados sin estructura")
    ap.add_argument("--dry-run", action="store_true",
                    help="solo cuenta y lista los genes; no descarga nada")
    ap.add_argument("--prune", action="store_true",
                    help="borra los *_AF.cif de --out-dir que NO están en index.json "
                         "(con --dry-run solo los lista)")
    ap.add_argument("--uniprot", action="append", default=[], metavar="GEN=ACC",
                    help="fija el acceso UniProt de un gen (repetible)")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "structures" / "external")
    ap.add_argument("--force", action="store_true", help="re-descargar aunque el CIF exista")
    args = ap.parse_args()

    if args.prune:
        index_path = args.out_dir / "index.json"
        index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
        keep = {entry["file"] for entry in index.values()}
        orphans = sorted(p for p in args.out_dir.glob("*_AF.cif") if p.name not in keep)
        size_mb = sum(p.stat().st_size for p in orphans) / 1024 / 1024
        print(f"▶ {len(orphans)} CIF fuera del índice ({size_mb:.0f} MB); "
              f"se conservan {len(keep)} del índice")
        if not args.dry_run:
            for p in orphans:
                p.unlink()
            print("  ✓ borrados")
        else:
            print("  (dry-run: no se borró nada)")
        return 0

    genes = [g.strip().upper() for g in (args.genes or "").split(",") if g.strip()]
    if args.from_data:
        genes += [g for g in genes_without_structure(args.from_data, args.top) if g not in genes]
    if not genes:
        ap.error("indica --genes o --from-data")
    if args.dry_run:
        print(f"▶ {len(genes)} gen(es) se descargarían (~1 MB cada uno):")
        print("  " + ", ".join(genes))
        return 0

    overrides = {}
    for item in args.uniprot:
        gene, _, acc = item.partition("=")
        if not acc:
            ap.error(f"--uniprot espera GEN=ACC, no '{item}'")
        overrides[gene.strip().upper()] = acc.strip()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    index_path = args.out_dir / "index.json"
    index = {}
    if index_path.is_file():
        try:
            index = json.loads(index_path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            index = {}

    failures = []
    print(f"▶ Descargando {len(genes)} gen(es) de AlphaFold DB → {args.out_dir}")
    for gene in genes:
        try:
            acc = overrides.get(gene) or lookup_uniprot(gene)
            if not acc:
                raise RuntimeError("sin acceso UniProt revisado (usa --uniprot GEN=ACC)")
            index[gene] = fetch_gene(gene, acc, args.out_dir, args.force)
        except Exception as exc:   # noqa: BLE001 — se informa y se sigue con el resto
            failures.append(gene)
            print(f"  ✗ {gene}: {exc}", file=sys.stderr)

    tmp = index_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(index_path)
    print(f"▶ Índice actualizado: {index_path} ({len(index)} gen(es))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
