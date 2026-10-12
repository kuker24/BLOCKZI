import json
import subprocess
import threading
import time

proc = subprocess.Popen(
    ['node', '/home/fahmi/.npm/_npx/d2b21a18eddad784/node_modules/scrcpy-mcp/dist/index.js'],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    bufsize=1
)

def print_stderr():
    for line in iter(proc.stderr.readline, ''):
        print(f"[scrcpy-mcp stderr] {line.strip()}")

threading.Thread(target=print_stderr, daemon=True).start()

def send_notify(msg):
    req_str = json.dumps(msg) + '\n'
    proc.stdin.write(req_str)
    proc.stdin.flush()

def send_req(msg):
    req_str = json.dumps(msg) + '\n'
    proc.stdin.write(req_str)
    proc.stdin.flush()
    res = proc.stdout.readline()
    return json.loads(res)

print("1. Initialize MCP...")
init_res = send_req({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0"}
    }
})
print("Init response:", init_res)

send_notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

print("2. Call start_session...")
t0 = time.time()
start_res = send_req({
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "start_session",
        "arguments": {}
    }
})
t1 = time.time()
print(f"start_session finished in {t1 - t0:.3f}s")

print("3. Test take_screenshot latency...")
t_ss_0 = time.time()
shot_res = send_req({
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
        "name": "take_screenshot",
        "arguments": {}
    }
})
t_ss_1 = time.time()
print(f"take_screenshot latency: {(t_ss_1 - t_ss_0)*1000:.1f} ms")

print("4. Benchmark 5 consecutive screenshots...")
times = []
for i in range(5):
    t_start = time.time()
    send_req({
        "jsonrpc": "2.0",
        "id": 10 + i,
        "method": "tools/call",
        "params": {
            "name": "take_screenshot",
            "arguments": {}
        }
    })
    times.append((time.time() - t_start) * 1000)
print(f"Screenshot latencies: {[round(x, 1) for x in times]} ms (Avg: {sum(times)/len(times):.1f} ms)")

print("5. Benchmark tap/swipe latency in scrcpy-mcp...")
# Let's inspect drag_drop tool schema
tools_res = send_req({
    "jsonrpc": "2.0",
    "id": 20,
    "method": "tools/list",
    "params": {}
})
for tool in tools_res['result']['tools']:
    if tool['name'] in ['tap', 'swipe', 'drag_drop']:
        print(f"Tool {tool['name']}: {tool['description']}")

proc.terminate()
