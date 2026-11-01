import urllib.request, json
req = urllib.request.urlopen("http://localhost:5000/api/2.0/mlflow/artifacts/list?run_id=141938c0fa474400b473284f19fab64c")
print("Ingest artifacts:", json.loads(req.read()))

req = urllib.request.urlopen("http://localhost:5000/api/2.0/mlflow/runs/get?run_id=141938c0fa474400b473284f19fab64c")
run_data = json.loads(req.read())
print("Inputs (datasets):", run_data["run"].get("inputs", {}))
