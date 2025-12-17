import json, requests
with open("real_test_params.json", "r") as f:
    data = json.load(f)
r = requests.post("http://127.0.0.1:8080/", json=data)
print(r.status_code, r.text)
