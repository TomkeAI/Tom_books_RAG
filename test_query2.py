import urllib.request, json
d = json.dumps({"query": "芒格的思维模型网格是什么"}).encode("utf-8")
req = urllib.request.Request("http://localhost:8000/api/chat/stream", data=d, headers={"Content-Type": "application/json"})
resp = urllib.request.urlopen(req)
body = resp.read().decode("utf-8")
# 打印 contain "sources" or "status" 的行
for line in body.split("\n"):
    if '"sources"' in line or '"status"' in line or '"target_book"' in line or '"type"' in line:
        print(line[:200])
