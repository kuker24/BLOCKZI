import json
import subprocess
import time

def test_scrcpy_mcp():
    proc = subprocess.Popen(
        ['node', '/home/fahmi/.npm/_npx/d2b21a18eddad784/node_modules/scrcpy-mcp/dist/index.js'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    
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
    print("Init response serverInfo:", init_res.get('result', {}).get('serverInfo'))

    send_req({"jsonrpc": "2.0", "method": "notifications/initialized"})

    print("2. Call list_tools...")
    tools_res = send_req({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {}
    })
    tools = [t['name'] for t in tools_res.get('result', {}).get('tools', [])]
    print(f"Total tools: {len(tools)}. Examples: {tools[:8]}")

    print("3. Start scrcpy session on device...")
    t0 = time.time()
    start_res = send_req({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "start_session",
            "arguments": {}
        }
    })
    t1 = time.time()
    print(f"Start session took {t1 - t0:.3f}s:")
    print(start_res)

    print("4. Test take_screenshot...")
    t2 = time.time()
    shot_res = send_req({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "take_screenshot",
            "arguments": {}
        }
    })
    t3 = time.time()
    content = shot_res.get('result', {}).get('content', [{}])[0]
    mime = content.get('mimeType', 'unknown')
    data_len = len(content.get('data', ''))
    print(f"Screenshot took {t3 - t2:.3f}s: mime={mime}, base64 len={data_len}")

    proc.terminate()

if __name__ == '__main__':
    test_scrcpy_mcp()
