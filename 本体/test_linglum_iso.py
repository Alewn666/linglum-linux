#!/usr/bin/env python3
"""灵珑系统 | Linglum Linux —— Live 盘引导验证（串口交互，必须显式加载 AAVMF 固件）

用法：python3 test_linglum_iso.py [--kvm]
判据：横幅(motd)出现 / shell 可用 / uname=7.3.0-rc7 / fb0 存在 / install-loongos 在
"""
import os
import re
import select
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ISO = os.path.join(HERE, "out", "linux.iso")
CODE = "/usr/share/AAVMF/AAVMF_CODE.fd"
VARS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "ling_vars_test.fd")
KVM = "--kvm" in sys.argv
BOOT_TIMEOUT = 220
ANSI = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>][0-9]?[a-zA-Z]?")

def qemu_cmd(extra=()):
    if KVM:
        base = ["sudo", "-n", "qemu-system-aarch64",
                "-machine", "virt,gic-version=3", "-accel", "kvm", "-cpu", "host"]
    else:
        base = ["qemu-system-aarch64", "-machine", "virt,gic-version=2", "-cpu", "cortex-a57"]
    return base + [
        "-m", "512", "-smp", "2",
        "-drive", f"if=pflash,format=raw,readonly=on,file={CODE}",
        "-drive", f"if=pflash,format=raw,file={VARS}",
        "-cdrom", ISO, "-nographic", "-no-reboot",
    ] + list(extra)

def main():
    if not os.path.exists(ISO):
        print("缺 ISO:", ISO); return 1
    subprocess.run(["cp", CODE.replace("CODE.fd", "VARS.fd"), VARS], check=False)
    print("== 启动", "KVM(GICv3)" if KVM else "TCG(GICv2)", "==")
    p = subprocess.Popen(qemu_cmd(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    os.set_blocking(p.stdout.fileno(), False)
    raw = b""
    t0 = time.time()
    checks, stage = [], 0
    try:
        while time.time() - t0 < BOOT_TIMEOUT:
            r, _, _ = select.select([p.stdout], [], [], 1.0)
            if r:
                raw += (p.stdout.read(65536) or b"")
            txt = ANSI.sub(b"", raw).decode("utf-8", "replace")
            if stage == 0 and "Linglum Linux" in txt and "#" in txt:
                checks.append(("live 横幅 + shell", True)); stage = 1
                p.stdin.write(b"uname -a\n"); p.stdin.flush(); time.sleep(4)
            elif stage == 1 and "7.3.0-rc7" in txt:
                checks.append(("uname = 7.3.0-rc7", True)); stage = 2
                p.stdin.write(b"ls /sys/class/graphics/ && ls /bin/install-loongos /loongos/disk.img\n")
                p.stdin.flush(); time.sleep(3)
            elif stage == 2 and "fb0" in txt and "install-loongos" in txt:
                checks.append(("fb0 帧缓冲 + 安装器就位", True)); stage = 3
                p.stdin.write(b"poweroff -f\n"); p.stdin.flush(); time.sleep(2)
                break
            if p.poll() is not None:
                break
    finally:
        if p.poll() is None:
            p.kill(); p.wait()
    if stage < 3:
        checks.append(("live 横幅 + shell", stage >= 1))
        if stage < 2: checks.append(("uname = 7.3.0-rc7", False))
        if stage < 3: checks.append(("fb0 帧缓冲 + 安装器就位", False))
    for n, c in checks:
        print(("✅" if c else "❌") + f" [{n}]")
    allok = all(c for _, c in checks)
    print("==", "ALL PASS" if allok else "FAIL", "==")
    if not allok:
        print("---- 串口尾部 ----")
        print(ANSI.sub(b"", raw).decode("utf-8", "replace")[-1500:])
    return 0 if allok else 1

if __name__ == "__main__":
    sys.exit(main())
