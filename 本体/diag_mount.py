#!/usr/bin/env python3
"""诊断：手动在 Live 里 mount /dev/sr0，看真实报错（替代盲猜）。"""
import os, re, select, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ISO = os.path.join(HERE, "out", "linux.iso")
CODE = "/usr/share/AAVMF/AAVMF_CODE.fd"
VARS_SRC = "/usr/share/AAVMF/AAVMF_VARS.fd"
DISK = os.path.join(HERE, "build", "smoke_disk.img")
ANSI = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>][0-9]?[a-zA-Z]?")

for line in open("/proc/meminfo"):
    if line.startswith("MemAvailable:"):
        if int(line.split()[1]) // 1024 < 450:
            print("内存不足"); sys.exit(2)

subprocess.run(["rm", "-f", DISK]); subprocess.run(["truncate", "-s", "512M", DISK], check=True)
varsf = os.path.join(HERE, "build", "smoke_vars.fd"); subprocess.run(["cp", VARS_SRC, varsf])
cmd = ["qemu-system-aarch64", "-machine", "virt,gic-version=2", "-cpu", "cortex-a57",
       "-m", "256", "-smp", "1",
       "-drive", f"if=pflash,format=raw,readonly=on,file={CODE}",
       "-drive", f"if=pflash,format=raw,file={varsf}",
       "-nographic", "-no-reboot",
       "-device", "virtio-scsi-pci,id=scsi0",
       "-drive", f"if=none,id=cd0,media=cdrom,readonly=on,file={ISO}",
       "-device", "scsi-cd,drive=cd0,bus=scsi0.0",
       "-drive", f"if=none,id=d0,format=raw,file={DISK}",
       "-device", "virtio-blk-pci,drive=d0"]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
os.set_blocking(p.stdout.fileno(), False)
raw = b""
def text():
    global raw
    while True:
        r, _, _ = select.select([p.stdout], [], [], 0.4)
        if not r: break
        c = p.stdout.read(65536)
        if not c: break
        raw += c
    return ANSI.sub(b"", raw).decode("utf-8", "replace")
def run(c, wait=4):
    p.stdin.write(c.encode() + b"\n"); p.stdin.flush(); time.sleep(wait)
    return text()

try:
    t0 = time.time()
    while time.time() - t0 < 200 and not re.search(r"/ # ", text()):
        time.sleep(0.3)
    print("== 进 shell ==", bool(re.search(r"/ # ", text())))
    for c in ["cat /proc/mounts | head -20",
              "ls -l /dev/sr0",
              "mkdir -p /mnt/t && mount /dev/sr0 /mnt/t; echo rc=$?",
              "mkdir -p /mnt/u && mount -t iso9660 -o ro /dev/sr0 /mnt/u; echo rc=$?",
              "mkdir -p /mnt/v && mount -t udf -o ro /dev/sr0 /mnt/v; echo rc=$?",
              "ls /mnt/t 2>&1 | head",
              "ls /mnt/u 2>&1 | head",
              "ls /mnt/v 2>&1 | head",
              "mount -t squashfs -o ro /dev/sr0 /mnt/v 2>&1; echo rc=$?",
              "cat /proc/filesystems | head -20",
              "ls /sys/block/ && cat /sys/block/sr0/device/type 2>&1"]:
        before = len(raw)
        run(c, 5)
        out = ANSI.sub(b"", raw[before:]).decode("utf-8", "replace")
        print("\n$ " + c); print(out.strip()[-800:])
finally:
    try: p.kill(); p.wait(timeout=5)
    except Exception: pass
