import urllib.request, json
d = json.dumps({"query": "芒格的思维模型网格是什么"}).encode("utf-8")
req = urllib.request.Request("http://localhost:8000/api/chat/stream", data=d, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
body = resp.read().decode("utf-8")
for line in body.split("\n"):
    if 'target_book' in line or ('"status"' in line and 'text' in line):
        print(line[6:])  # skip "data: "
