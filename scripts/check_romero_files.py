import json, glob, os
variants = json.load(open('tests/reference/romero_v2/top_variants.json'))
pdbs = set(os.path.basename(p) for p in glob.glob('tests/reference/romero_v2/structures/*.pdb'))
fastas = set(os.path.basename(p) for p in glob.glob('tests/reference/romero_v2/fasta/*.fasta'))
genes = set(x['hugo_symbol'] for x in variants)
print('WT files:')
for g in genes:
    print(g, 'pdb:', f'{g}_WT.pdb' in pdbs, 'fasta:', f'{g}_WT.fasta' in fastas)
missing = [f"{v['hugo_symbol']}_{v['protein_change']}" for v in variants if f"{v['hugo_symbol']}_{v['protein_change']}.pdb" not in pdbs]
print('Missing mut pdbs count:', len(missing), missing[:5])
missing_fa = [f"{v['hugo_symbol']}_{v['protein_change']}" for v in variants if f"{v['hugo_symbol']}_{v['protein_change']}.fasta" not in fastas]
print('Missing mut fastas count:', len(missing_fa), missing_fa[:5])

