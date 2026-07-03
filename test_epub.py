import urllib.request, json

d = json.dumps({"query": "记忆红利是什么"}).encode("utf-8")
req = urllib.request.Request(
    "http://localhost:8000/api/chat/stream", data=d,
    headers={"Content-Type": "application/json"}
)
resp = urllib.request.urlopen(req)
body = resp.read().decode("utf-8")

for line in body.split("\n"):
    if line.startswith("data:") and "sources" in line:
        data = json.loads(line[6:])
        print(f"来源类型: {data.get('source_type', '?')}")
        for s in data["sources"]:
            print(f"  《{s['book']}》— {s['chapter']} (score: {s['score']})")
