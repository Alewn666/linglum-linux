#!/usr/bin/env python3
"""端到端验收：Linux Live 盘 → 安装 LoongOS → 从硬盘启动进 LoongOS

阶段 A：Live 盘启动（带一块空白 virtio 硬盘）→ 执行 install-loongos → 确认写入
阶段 B：只挂硬盘（不放安装盘）→ 应直接进入 LoongOS（横幅 + shell）

用法：python3 test_install_e2e.py [--kvm]
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
VARS_SRC = "/usr/share/AAVMF/AAVMF_VARS.fd"
DISK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "e2e_disk.img")
KVM = "--kvm" in sys.argv
ANSI = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>][0-9]?[a-zA-Z]?")

def base_machine(tag):
    if KVM:
        return ["sudo", "-n", "qemu-system-aarch64",
                "-machine", "virt,gic-version=3", "-accel", "kvm", "-cpu", "host"]
    return ["qemu-system-aarch64", "-machine", "virt,gic-version=2", "-cpu", "cortex-a57"]

class VM:
    def __init__(self, extra, tag):
        varsf = os.path.join(HERE, "build", f"ling_vars_{tag}.fd")
        subprocess.run(["cp", VARS_SRC, varsf], check=False)
        cmd = base_machine(tag) + [
            "-m", "512", "-smp", "2",
            "-drive", f"if=pflash,format=raw,readonly=on,file={CODE}",
            "-drive", f"if=pflash,format=raw,file={varsf}",
            "-nographic", "-no-reboot",
        ] + extra
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT)
        os.set_blocking(self.p.stdout.fileno(), False)
        self.raw = b""

    def text(self):
        while True:
            r, _, _ = select.select([self.p.stdout], [], [], 0.5)
            if not r:
                break
            c = self.p.stdout.read(65536)
            if not c:
                break
            self.raw += c
        return ANSI.sub(b"", self.raw).decode("utf-8", "replace")

    def wait(self, pattern, timeout, label):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if re.search(pattern, self.text()):
                print("  ✅ " + label); return True
            if self.p.poll() is not None:
                break
            time.sleep(0.3)
        print("  ❌ " + label); return False

    def send(self, s):
        try:
            self.p.stdin.write(s.encode() + b"\n"); self.p.stdin.flush()
        except Exception:
            pass

    def kill(self):
        try:
            if self.p.poll() is None:
                self.p.kill(); self.p.wait()
        except Exception:
            pass

def main():
    if not os.path.exists(ISO):
        print("缺 ISO:", ISO); return 1
    ok = []
    disk_arg = ["-drive", f"if=none,id=d0,format=raw,file={DISK}",
                "-device", "virtio-blk-pci,drive=d0"]

    # 空白硬盘 512MB
    subprocess.run(["rm", "-f", DISK])
    subprocess.run(["truncate", "-s", "512M", DISK], check=True)

    print("=== 阶段 A：Live 盘内安装 ===")
    vm = VM(["-cdrom", ISO] + disk_arg, "a")
    try:
        if not vm.wait(r"Linglum Linux[\s\S]*#", 220, "Live 环境就绪"):
            return 1
        ok.append(True)
        vm.send("ls /dev/vd*")
        time.sleep(2)
        if not vm.wait(r"/dev/vda", 10, "目标盘 /dev/vda 可见"):
            return 1
        ok.append(True)
        vm.send(f"install-loongos /dev/vda")
        if not vm.wait(r"to confirm", 15, "安装器确认提示"):
            return 1
        ok.append(True)
        vm.send("yes")
        ok2 = vm.wait(r"Installation complete|DONE: installed", 240, "LoongOS 写入完成")
        if not ok2:
            print("---- 串口尾部 ----")
            print(vm.text()[-2500:])
            return 1
        ok.append(True)
        time.sleep(2)
        vm.send("poweroff -f")
        time.sleep(4)
    finally:
        vm.kill()

    print("=== 阶段 B：只挂硬盘启动（不放安装盘）===")
    vm = VM(disk_arg, "b")
    try:
        if not vm.wait(r"灵珑系统[\s\S]*LoongOS", 90, "LoongOS 横幅（从硬盘引导）"):
            return 1
        ok.append(True)
        if not vm.wait(r"\n> ", 30, "LoongOS shell 提示符"):
            return 1
        ok.append(True)
        vm.send("whoami")
        time.sleep(2)
        t = vm.text()
        good = ("root" in t or "demo" in t)
        print(("  ✅ " if good else "  ❌ ") + "whoami 返回身份")
        ok.append(good)
        time.sleep(1)
    finally:
        vm.kill()

    print(f"\n== {'ALL PASS' if all(ok) else 'FAIL'} （{sum(ok)}/{len(ok)}）==")
    return 0 if all(ok) else 1

if __name__ == "__main__":
    sys.exit(main())
