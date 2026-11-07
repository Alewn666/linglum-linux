#!/usr/bin/env python3
"""端到端验收：Linglum Live 盘 → install-linglum 自装到硬盘 → 从硬盘启动 → 持久化

阶段 A：Live 盘启动（带一块空白 virtio 硬盘）→ install-linglum /dev/vda → 确认写入
阶段 B：只挂硬盘（不放安装盘）→ 进 Linglum → 写 /home/persist.txt → poweroff
阶段 C：再只挂硬盘启动 → /home/persist.txt 仍在且内容对（=真持久化）

用法：python3 test_linglum_install.py [--kvm]
TCG 用 -m 400（Live initrd 现在 24MB）；KVM 用同样内存。
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
DISK = os.path.join(HERE, "build", "ling_e2e_disk.img")
KVM = "--kvm" in sys.argv
MEM = "400"
ANSI = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>][0-9]?[a-zA-Z]?")


def base_machine():
    if KVM:
        return ["sudo", "-n", "qemu-system-aarch64",
                "-machine", "virt,gic-version=3", "-accel", "kvm", "-cpu", "host"]
    return ["qemu-system-aarch64", "-machine", "virt,gic-version=2", "-cpu", "cortex-a57"]


class VM:
    def __init__(self, extra, tag):
        varsf = os.path.join(HERE, "build", f"le2e_vars_{tag}.fd")
        subprocess.run(["cp", VARS_SRC, varsf], check=False)
        cmd = base_machine() + [
            "-m", MEM, "-smp", "1",
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

    print("=== 阶段 A：Live 盘内安装 Linglum ===")
    vm = VM(["-cdrom", ISO] + disk_arg, "a")
    try:
        if not vm.wait(r"Linglum Linux[\s\S]*#", 260, "Live 环境就绪"):
            return 1
        ok.append(True)
        vm.send("ls /dev/vd*")
        time.sleep(2)
        if not vm.wait(r"/dev/vda", 10, "目标盘 /dev/vda 可见"):
            return 1
        ok.append(True)
        vm.send("install-linglum /dev/vda")
        if not vm.wait(r"to confirm", 20, "安装器确认提示"):
            print("---- 串口尾部 ----"); print(vm.text()[-2000:]); return 1
        ok.append(True)
        vm.send("yes")
        # 194MB 含真实内核/GRUB/ext4 数据，TCG 流式解压+写盘比 LoongOS(129MB 全零)慢得多
        if not vm.wait(r"Installation complete|DONE: installed", 600, "Linglum 写入完成"):
            print("---- 串口尾部 ----"); print(vm.text()[-2500:]); return 1
        ok.append(True)
        time.sleep(2)
        vm.send("poweroff -f")
        time.sleep(4)
    finally:
        vm.kill()

    print("=== 阶段 B：只挂硬盘启动 → 写持久化文件 ===")
    vm = VM(disk_arg, "b")
    try:
        if not vm.wait(r"Linglum Linux[\s\S]*#", 120, "从硬盘进入 Linglum"):
            print("---- 串口尾部 ----"); print(vm.text()[-2500:]); return 1
        ok.append(True)
        # 确认真在 ext4 根上（不是 initramfs）
        vm.send("mount | grep ' / ' ; cat /proc/mounts | grep ' / ' | head -1")
        time.sleep(2)
        t = vm.text()
        on_ext4 = ("ext4" in t)
        print(("  ✅ " if on_ext4 else "  ❌ ") + "根文件系统是 ext4（真从硬盘跑）")
        ok.append(on_ext4)
        # 写持久化文件
        vm.send("echo hello-linglum-persist > /home/persist.txt")
        time.sleep(2)
        vm.send("cat /home/persist.txt")
        if not vm.wait(r"hello-linglum-persist", 15, "写入并读回 /home/persist.txt"):
            print("---- 串口尾部 ----"); print(vm.text()[-2000:]); return 1
        ok.append(True)
        time.sleep(1)
        vm.send("poweroff -f")
        time.sleep(4)
    finally:
        vm.kill()

    print("=== 阶段 C：再次从硬盘启动 → 验证文件还在（持久化）===")
    vm = VM(disk_arg, "c")
    try:
        if not vm.wait(r"Linglum Linux[\s\S]*#", 120, "再次从硬盘进入 Linglum"):
            return 1
        ok.append(True)
        vm.send("cat /home/persist.txt")
        if not vm.wait(r"hello-linglum-persist", 20, "重启后 /home/persist.txt 仍在（持久化成功）"):
            print("---- 串口尾部 ----"); print(vm.text()[-2500:]); return 1
        ok.append(True)
        time.sleep(1)
    finally:
        vm.kill()

    print(f"\n== {'ALL PASS' if all(ok) else 'FAIL'} （{sum(ok)}/{len(ok)}）==")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
