"""测试流式 RAG 两次连续问答"""
import urllib.request
import json

url = "http://localhost:8000/api/chat/stream"

for i, q in enumerate(["Die with Zero的核心思想", "如何克服冒充者综合征"], 1):
    data = json.dumps({"query": q}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        body = resp.read().decode()
        tokens = [l for l in body.split("\n") if l.startswith("data: ")]
        conv_id = None
        source_count = 0
        for t in tokens:
            evt = json.loads(t[6:])
            if evt["type"] == "conv":
                conv_id = evt["id"]
            elif evt["type"] == "sources":
                source_count = len(evt["sources"])
        print(f"第{i}次问答 OK | conv={conv_id} | 来源={source_count}")
    except Exception as e:
        print(f"第{i}次问答 失败: {e}")
