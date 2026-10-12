import base64
import io
import json
import subprocess
import time
from PIL import Image

def test_mcp_vision():
    proc = subprocess.Popen(
        ['node', '/home/fahmi/.npm/_npx/d2b21a18eddad784/node_modules/scrcpy-mcp/dist/index.js'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    def send_notify(msg):
        proc.stdin.write(json.dumps(msg) + '\n')
        proc.stdin.flush()

    def send_req(msg):
        proc.stdin.write(json.dumps(msg) + '\n')
        proc.stdin.flush()
        res = proc.stdout.readline()
        return json.loads(res)

    print("1. Initialize scrcpy-mcp...")
    send_req({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "benchmark", "version": "1.0"}
        }
    })
    send_notify({"jsonrpc": "2.0", "method": "notifications/initialized"})

    print("2. Start scrcpy session...")
    t0 = time.time()
    send_req({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "start_session", "arguments": {}}
    })
    print(f"Session started in {time.time() - t0:.3f}s")

    print("3. Capture and decode frame via scrcpy-mcp...")
    t_cap_0 = time.time()
    res = send_req({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "take_screenshot", "arguments": {}}
    })
    t_cap_1 = time.time()

    b64_data = res['result']['content'][0]['data']
    img_bytes = base64.b64decode(b64_data)
    im = Image.open(io.BytesIO(img_bytes))
    t_decode = time.time()

    print(f"Frame fetch time: {(t_cap_1 - t_cap_0)*1000:.1f} ms")
    print(f"Frame decode time: {(t_decode - t_cap_1)*1000:.1f} ms")
    print(f"Decoded image size: {im.size}, mode: {im.mode}")
    im.save('/tmp/antigravity/mcp_frame.jpg')

    proc.terminate()

if __name__ == '__main__':
    test_mcp_vision()
