import urllib.request, json

d = json.dumps({"query": "芒格的思维模型网格"}).encode("utf-8")
req = urllib.request.Request(
    "http://localhost:8000/api/chat/stream", data=d,
    headers={"Content-Type": "application/json"}
)
resp = urllib.request.urlopen(req)
body = resp.read().decode("utf-8")

for line in body.split("\n"):
    if line.startswith("data:") and "sources" in line:
        data = json.loads(line[6:])
        print(f"target_book: {data.get('target_book')}")
        for s in data["sources"][:3]:
            print(f"  书: {s['book']}  章: {s['chapter']}")
