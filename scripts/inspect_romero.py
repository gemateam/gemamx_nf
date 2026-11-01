import json

metrics = json.load(open("tests/reference/romero_v2/structural_metrics.json"))
print("Type:", type(metrics))
first_key = next(iter(metrics))
print("First key:", first_key)
print("First val:", metrics[first_key])

vina = json.load(open("tests/reference/romero_v2/vina_affinities.json"))
print("Vina type:", type(vina))
if isinstance(vina, list):
    print("Vina count:", len(vina))
    print("First item:", vina[0])
elif isinstance(vina, dict):
    print("Vina keys count:", len(vina))
    vk = next(iter(vina))
    print("First vk:", vk, vina[vk])
