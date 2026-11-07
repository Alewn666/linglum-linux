#!/usr/bin/env python3
"""验证 Linglum 安装器的【向导路径】修复（子 shell 变量丢失 bug）。

2026-10-25 真机 bug：`install-loongos` 不带参数走向导时，磁盘列表全是空、Target 空，
写盘时报 "write failed at block 0"（dd of=""）。根因=list_disks 在 $( ) 子 shell 里
eval DISK_$n，出了子 shell 变量全丢。

本测试：
  A) Live 盘 + 空白 512MB virtio 盘 → `install-loongos`（不带参数）→
     期望列出带名字/容量的 /dev/vda → 选 1 → yes → Installation complete
  B) 只挂硬盘启动 → LoongOS 横幅 → `[fs  ] MOUNTED-DISK`（首次自动格式化）→ 写文件
  C) 再启动 → cat 文件仍在（持久化）

用法：python3 test_wizard_fix.py     （默认 TCG，-m 512，一次只起一个 VM）
"""
import os, re, select, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ISO = os.path.join(HERE, "out", "linux.iso")
CODE = "/usr/share/AAVMF/AAVMF_CODE.fd"
VARS_SRC = "/usr/share/AAVMF/AAVMF_VARS.fd"
DISK = os.path.join(HERE, "build", "wiz_disk.img")
ANSI = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>][0-9]?[a-zA-Z]?")


class VM:
    def __init__(self, extra, tag):
        varsf = os.path.join(HERE, "build", f"wiz_vars_{tag}.fd")
        subprocess.run(["cp", VARS_SRC, varsf], check=False)
        cmd = ["qemu-system-aarch64", "-machine", "virt,gic-version=2", "-cpu", "cortex-a57",
               "-m", "320", "-smp", "1",
               "-drive", f"if=pflash,format=raw,readonly=on,file={CODE}",
               "-drive", f"if=pflash,format=raw,file={varsf}",
               "-nographic", "-no-reboot"] + extra
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT)
        os.set_blocking(self.p.stdout.fileno(), False)
        self.raw = b""

    def text(self):
        while True:
            r, _, _ = select.select([self.p.stdout], [], [], 0.4)
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
                print("  ✅ " + label, flush=True)
                return True
            if self.p.poll() is not None:
                break
            time.sleep(0.3)
        print("  ❌ " + label, flush=True)
        return False

    def send(self, s):
        try:
            self.p.stdin.write(s.encode() + b"\n")
            self.p.stdin.flush()
        except Exception:
            pass

    def kill(self):
        try:
            if self.p.poll() is None:
                self.p.kill(); self.p.wait()
        except Exception:
            pass


def mem_ok():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            mb = int(line.split()[1]) // 1024
            print("可用内存 %d MB（门槛 450）" % mb, flush=True)
            return mb >= 500
    return True


def main():
    if not mem_ok():
        print("✗ 可用内存不足，拒绝起虚拟机（防止再次拖垮 NAS）")
        return 2
    if not os.path.exists(ISO):
        print("缺 ISO:", ISO); return 1
    ok = []
    disk_arg = ["-drive", f"if=none,id=d0,format=raw,file={DISK}",
                "-device", "virtio-blk-pci,drive=d0"]
    subprocess.run(["rm", "-f", DISK])
    subprocess.run(["truncate", "-s", "512M", DISK], check=True)

    print("=== A：向导安装 ===", flush=True)
    vm = VM(["-device", "virtio-scsi-pci,id=scsi0",
             "-drive", f"if=none,id=cd0,media=cdrom,readonly=on,file={ISO}",
             "-device", "scsi-cd,drive=cd0,bus=scsi0.0"] + disk_arg, "a")
    try:
        if not vm.wait(r"Linglum Linux[\s\S]*#", 240, "Live 就绪"):
            return 1
        ok.append(True)
        vm.send("install-loongos")                      # ← 不带参数：走向导
        if not vm.wait(r"Available disks", 20, "显示磁盘列表"):
            tail = vm.text()[-2500:]
            print("---- 串口尾部 ----"); print(tail)
            print("---- QEMU 状态 ----", vm.p.poll())
            return 1
        ok.append(True)
        t = vm.text()
        m = re.search(r"1\)\s+(\S+)\s+([0-9]+ (?:GB|MB))", t)
        good = bool(m and m.group(1) == "/dev/vda")
        print(("  ✅ " if good else "  ❌ ") + "列表里有 /dev/vda 且带容量" +
              ("  → %s %s" % m.groups() if m else "（没匹配到）"), flush=True)
        ok.append(good)
        if not good:
            print(vm.text()[-1500:]); return 1
        vm.send("1")
        if not vm.wait(r"Target : \S*/dev/vda", 15, "Target 正确解析为 /dev/vda"):
            print(vm.text()[-800:]); return 1
        ok.append(True)
        vm.send("yes")
        if not vm.wait(r"Installation complete|DONE: installed", 300, "写入完成"):
            print(vm.text()[-2000:]); return 1
        ok.append(True)
        time.sleep(1)
        vm.send("poweroff -f")
        time.sleep(4)
    finally:
        vm.kill()

    print("=== B：只挂硬盘启动（首次自动格式化数据分区）===", flush=True)
    vm = VM(disk_arg, "b")
    try:
        if not vm.wait(r"LoongOS", 120, "LoongOS 横幅"):
            return 1
        ok.append(True)
        if not vm.wait(r"\n> ", 30, "shell 提示符"):
            return 1
        ok.append(True)
        good = bool(re.search(r"\[fs  \] MOUNTED-DISK lba=\d+ blocks=\d+", vm.text()))
        print(("  ✅ " if good else "  ❌ ") + "自动格式化并挂载持久分区", flush=True)
        ok.append(good)
        vm.send("write /home/w.txt hello-wizard")
        time.sleep(3)
        vm.send("cat /home/w.txt")
        time.sleep(2)
        good2 = "hello-wizard" in vm.text()
        print(("  ✅ " if good2 else "  ❌ ") + "写入 /home/w.txt 并读回", flush=True)
        ok.append(good2)
        time.sleep(1)
    finally:
        vm.kill()

    print("=== C：重启验证持久化 ===", flush=True)
    vm = VM(disk_arg, "c")
    try:
        if not vm.wait(r"\n> ", 120, "再次进 shell"):
            return 1
        ok.append(True)
        mark = len(vm.raw)
        vm.send("cat /home/w.txt")
        time.sleep(3)
        good = "hello-wizard" in vm.text()[mark:]
        print(("  ✅ " if good else "  ❌ ") + "重启后文件还在", flush=True)
        ok.append(good)
    finally:
        vm.kill()

    print("\n== %s （%d/%d）==" % ("ALL PASS" if all(ok) else "FAIL", sum(ok), len(ok)))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
