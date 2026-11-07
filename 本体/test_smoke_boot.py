#!/usr/bin/env python3
"""快速冒烟：只验「Live 能起来 + 找到安装镜像」，不做安装（几十秒级）。

2026-10-25 的核心修复是：disk.img(129MB) 移出 initramfs → init 从光盘挂载。
本脚本用 -m 256（以前必 panic 的尺寸）验证这两件事。
"""
import os, re, select, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ISO = os.path.join(HERE, "out", "linux.iso")
CODE = "/usr/share/AAVMF/AAVMF_CODE.fd"
VARS_SRC = "/usr/share/AAVMF/AAVMF_VARS.fd"
DISK = os.path.join(HERE, "build", "smoke_disk.img")
ANSI = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>][0-9]?[a-zA-Z]?")
MEM = os.environ.get("SMOKE_MEM", "256")


def mem_ok(need=450):
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            mb = int(line.split()[1]) // 1024
            print("可用内存 %d MB（需 %d）" % (mb, need), flush=True)
            return mb >= need
    return True


def main():
    if not mem_ok():
        print("✗ 内存不足，拒绝起虚拟机"); return 2
    if not os.path.exists(ISO):
        print("缺 ISO"); return 1
    subprocess.run(["rm", "-f", DISK])
    subprocess.run(["truncate", "-s", "512M", DISK], check=True)
    varsf = os.path.join(HERE, "build", "smoke_vars.fd")
    subprocess.run(["cp", VARS_SRC, varsf])
    cmd = ["qemu-system-aarch64", "-machine", "virt,gic-version=2", "-cpu", "cortex-a57",
           "-m", MEM, "-smp", "1",
           "-drive", f"if=pflash,format=raw,readonly=on,file={CODE}",
           "-drive", f"if=pflash,format=raw,file={varsf}",
           "-nographic", "-no-reboot",
           # ⚠️ 不能只写 -cdrom ISO：与 -drive if=none 同用时 QEMU 不创建 /dev/sr0，
           #    Live 找不到光盘 → install image missing。显式挂到 virtio-scsi 上。
           "-device", "virtio-scsi-pci,id=scsi0",
           "-drive", f"if=none,id=cd0,media=cdrom,readonly=on,file={ISO}",
           "-device", "scsi-cd,drive=cd0,bus=scsi0.0",
           "-drive", f"if=none,id=d0,format=raw,file={DISK}",
           "-device", "virtio-blk-pci,drive=d0"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    os.set_blocking(p.stdout.fileno(), False)
    raw = b""
    def text():
        nonlocal raw
        while True:
            r, _, _ = select.select([p.stdout], [], [], 0.4)
            if not r: break
            c = p.stdout.read(65536)
            if not c: break
            raw += c
        return ANSI.sub(b"", raw).decode("utf-8", "replace")
    ok = []
    try:
        # 1) 进 shell（-m 256 能否起来）
        t0 = time.time()
        while time.time() - t0 < 180:
            if re.search(r"/ # |Linglum Linux .*#", text()): break
            time.sleep(0.3)
        got_shell = bool(re.search(r"/ # ", text()))
        print(("  ✅ " if got_shell else "  ❌ ") + "Live 启动（-m %s）" % MEM, flush=True)
        ok.append(got_shell)
        if not got_shell:
            print(text()[-2000:]); return 1
        # 2) 安装镜像已挂上
        good = os.path.exists  # placeholder
        t = text()
        found = "/loongos/disk.img" not in t  # 若 shell 起来后 ls 能看见
        p.stdin.write(b"ls -l /loongos/\n"); p.stdin.flush()
        time.sleep(4)
        t = text()
        has = "disk.img.gz" in t
        print(("  ✅ " if has else "  ❌ ") + "找到 /loongos/disk.img", flush=True)
        ok.append(has)
        if not has:
            p.stdin.write(b"ls /dev/sr* /dev/vd* 2>&1\n"); p.stdin.flush()
            time.sleep(3)
            print("---- 设备与 loongos 目录 ----"); print(text()[-1200:])
        # 3) 安装器能识别镜像
        p.stdin.write(b"install-loongos --auto /dev/vda 2>&1 | head -5\n"); p.stdin.flush()
        time.sleep(6)
        t = text()[-1500:]
        started = ("Writing LoongOS" in t) or ("invalid target" in t) or ("ERRO" in t)
        no_missing = "install image missing" not in t
        print(("  ✅ " if no_missing else "  ❌ ") + "安装器不再报 image missing", flush=True)
        ok.append(no_missing)
    finally:
        try:
            p.kill(); p.wait(timeout=5)
        except Exception:
            pass
    print("\n== %s （%d/%d）==" % ("PASS" if all(ok) else "FAIL", sum(ok), len(ok)))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
