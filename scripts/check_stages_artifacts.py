import urllib.request, json

stages = ['ingest', 'fasta', 'structures', 'docking', 'metrics', 'publish']
run_name = 'romero_v2_20261101_030639'

req2 = urllib.request.Request("http://localhost:5000/api/2.0/mlflow/runs/search", 
                              data=json.dumps({"experiment_ids": ["5"], "max_results": 20}).encode("utf-8"), 
                              headers={"Content-Type": "application/json"})
runs = json.loads(urllib.request.urlopen(req2).read()).get("runs", [])

for r in runs:
    rname = r["info"]["run_name"]
    rid = r["info"]["run_id"]
    if rname.startswith(run_name):
        art_req = urllib.request.urlopen(f"http://localhost:5000/api/2.0/mlflow/artifacts/list?run_id={rid}")
        arts = [a["path"] for a in json.loads(art_req.read()).get("files", [])]
        print(f"{rname:35} | {rid} | {arts}")

