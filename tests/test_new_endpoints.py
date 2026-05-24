"""测试 API 端点（需要运行中 server）"""
import urllib.request
import json
import sys

BASE = "http://localhost:8001"
passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"[PASS] {name}")
        passed += 1
    except Exception as e:
        print(f"[FAIL] {name}: {e}")
        failed += 1

def api_get(path):
    resp = urllib.request.urlopen(f"{BASE}{path}")
    return json.loads(resp.read())

def api_post(path, body):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    result = {"status": resp.status, "events": []}
    decoder = resp.read().decode("utf-8")
    for line in decoder.split("\n"):
        if line.startswith("event: "):
            result["events"].append({"type": line[7:].strip()})
        elif line.startswith("data: "):
            try:
                result["events"][-1]["data"] = json.loads(line[6:])
            except:
                result["events"][-1]["data"] = line[6:]
    return result

# ── Test 1: GET /api/workflows (Phase 1 后返回空列表) ──
def t1():
    data = api_get("/api/workflows")
    wfs = data["workflows"]
    assert len(wfs) == 0, f"Expected 0 workflows, got {len(wfs)}"

test("GET /api/workflows (Phase 1 后返回空列表)", t1)

# ── Test 2: GET / (前端页面) ──
def t2():
    resp = urllib.request.urlopen(f"{BASE}/")
    html = resp.read().decode("utf-8")
    assert "app" in html.lower() or "<!doctype" in html.lower()
    assert resp.status == 200

test("GET / (前端页面正常)", t2)

# ── Test 3: POST /api/chat SSE (统一 Solo Agent) ──
def t3():
    result = api_post("/api/chat", {
        "message": "你好，简单介绍一下你能做什么",
        "thread_id": "test-solo-1",
    })
    assert result["status"] == 200
    event_types = [e["type"] for e in result["events"] if e.get("type")]
    assert len(event_types) > 0
    print(f"  收到 {len(result['events'])} 个事件: {event_types[:5]}...")

test("POST /api/chat (统一 Solo Agent SSE 正常)", t3)

# ── Summary ──
print()
print(f"总计: {passed} 通过, {failed} 失败")
if failed > 0:
    sys.exit(1)
