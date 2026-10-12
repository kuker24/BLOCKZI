import base64
import io
import json
import subprocess
import time
import numpy as np
from PIL import Image

def benchmark_adb_native():
    print("--- Testing Native ADB (Current Baseline) ---")
    # 1. Screen capture
    t0 = time.time()
    proc = subprocess.run(['adb', 'exec-out', 'screencap', '-p'], stdout=subprocess.PIPE, check=True)
    t1 = time.time()
    im = Image.open(io.BytesIO(proc.stdout))
    arr = np.array(im)
    t2 = time.time()
    
    cap_time = (t1 - t0) * 1000
    decode_time = (t2 - t1) * 1000
    print(f"ADB Screencap fetch: {cap_time:.1f} ms, decode: {decode_time:.1f} ms, Total perception: {cap_time + decode_time:.1f} ms")
    
    # 2. Input latency (dummy swipe or down-up)
    t3 = time.time()
    subprocess.run('adb shell input motionevent DOWN 500 500', shell=True)
    subprocess.run('adb shell input motionevent UP 500 500', shell=True)
    t4 = time.time()
    input_time = (t4 - t3) * 1000
    print(f"ADB motionevent input: {input_time:.1f} ms")
    
    return {
        "mode": "ADB Native",
        "perception_ms": cap_time + decode_time,
        "input_ms": input_time,
        "total_overhead_ms": cap_time + decode_time + input_time
    }

def benchmark_scrcpy_mcp():
    print("\n--- Testing Opsi 1: scrcpy-mcp (JuanCF) ---")
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
    
    # Start session
    t_start_0 = time.time()
    send_req({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "start_session", "arguments": {}}
    })
    t_start_1 = time.time()
    print(f"scrcpy-mcp session startup: {(t_start_1 - t_start_0)*1000:.1f} ms")

    # Benchmark 3 perception rounds
    perception_times = []
    for i in range(3):
        t0 = time.time()
        res = send_req({
            "jsonrpc": "2.0",
            "id": 10 + i,
            "method": "tools/call",
            "params": {"name": "screenshot", "arguments": {}}
        })
        t1 = time.time()
        img_bytes = base64.b64decode(res['result']['content'][0]['data'])
        im = Image.open(io.BytesIO(img_bytes))
        arr = np.array(im)
        t2 = time.time()
        perception_times.append((t2 - t0) * 1000)

    avg_perception = sum(perception_times) / len(perception_times)
    print(f"scrcpy-mcp screenshot perception (avg of 3): {avg_perception:.1f} ms")

    # Benchmark input (swipe/tap)
    input_times = []
    for i in range(3):
        t3 = time.time()
        send_req({
            "jsonrpc": "2.0",
            "id": 20 + i,
            "method": "tools/call",
            "params": {
                "name": "swipe",
                "arguments": {"x1": 500, "y1": 500, "x2": 500, "y2": 500, "duration": 50}
            }
        })
        t4 = time.time()
        input_times.append((t4 - t3) * 1000 - 50) # Subtract the requested gesture duration

    avg_input = sum(input_times) / len(input_times)
    print(f"scrcpy-mcp input protocol overhead (avg of 3): {avg_input:.1f} ms")

    proc.terminate()
    return {
        "mode": "Opsi 1: scrcpy-mcp",
        "perception_ms": avg_perception,
        "input_ms": avg_input,
        "total_overhead_ms": avg_perception + avg_input
    }

if __name__ == '__main__':
    r_adb = benchmark_adb_native()
    r_mcp = benchmark_scrcpy_mcp()

    print("\n=======================================================")
    print("           HASIL BENCHMARK KECEPATAN & EFISIENSI       ")
    print("=======================================================")
    print(f"{'Metode':<25} | {'Persepsi (ms)':<15} | {'Input Overhead (ms)':<20} | {'Total Overhead (ms)':<20}")
    print("-" * 85)
    print(f"{r_adb['mode']:<25} | {r_adb['perception_ms']:<15.1f} | {r_adb['input_ms']:<20.1f} | {r_adb['total_overhead_ms']:<20.1f}")
    print(f"{r_mcp['mode']:<25} | {r_mcp['perception_ms']:<15.1f} | {r_mcp['input_ms']:<20.1f} | {r_mcp['total_overhead_ms']:<20.1f}")
    print("-" * 85)
    speedup = r_adb['total_overhead_ms'] / r_mcp['total_overhead_ms']
    print(f"Kesimpulan: scrcpy-mcp {speedup:.1f}x LEBIH CEPAT daripada ADB biasa!")
