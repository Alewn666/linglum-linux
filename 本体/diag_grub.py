#!/usr/bin/env python3
"""诊断：磁盘镜像引导落到 grub> 时，GRUB 到底看到了什么。
Boot the installed disk under KVM, drop into grub>, probe root + files.
"""
import os, re, select, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
CODE = "/usr/share/AAVMF/AAVMF_CODE.fd"
VARS_SRC = "/usr/share/AAVMF/AAVMF_VARS.fd"
DISK = os.path.join(HERE, "build", "ling_e2e_disk.img")
ANSI = re.compile(rb"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>][0-9]?[a-zA-Z]?")

def main():
    varsf = os.path.join(HERE, "build", "grubdbg_vars.fd")
    subprocess.run(["cp", VARS_SRC, varsf], check=False)
    cmd = ["sudo", "-n", "qemu-system-aarch64",
           "-machine", "virt,gic-version=3", "-accel", "kvm", "-cpu", "host",
           "-m", "400", "-smp", "1",
           "-drive", f"if=pflash,format=raw,readonly=on,file={CODE}",
           "-drive", f"if=pflash,format=raw,file={varsf}",
           "-nographic", "-no-reboot",
           "-drive", f"if=none,id=d0,format=raw,file={DISK}",
           "-device", "virtio-blk-pci,drive=d0"]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
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
    def wait(pat, to):
        t0 = time.time()
        while time.time() - t0 < to:
            if re.search(pat, text()): return True
            if p.poll() is not None: return False
            time.sleep(0.2)
        return False
    def send(s):
        try: p.stdin.write(s.encode()+b"\n"); p.stdin.flush()
        except Exception: pass
    try:
        if not wait(r"grub>|GNU GRUB", 40):
            print("没到 GRUB"); print(text()[-1500:]); return 1
        time.sleep(1)
        # 逐条探查（目标：确证 prefix 值 + memdisk 结构 + normal 能否自动找配置）
        probes = [
            ("echo ROOT=[$root]", "root"),
            ("echo PREFIX=[$prefix]", "prefix（GRUB 去哪找配置）"),
            ("echo CFGPATH=[$prefix/grub.cfg]", "GRUB 期望的配置路径"),
            ("ls /", "memdisk 根"),
            ("ls /boot", "memdisk /boot"),
            ("ls /boot/grub", "memdisk /boot/grub"),
            ("ls ($prefix)", "GRUB prefix 目录里有什么"),
            ("normal", "手动跑 normal（能否自动出菜单）"),
        ]
        for cmdstr, label in probes:
            send(cmdstr)
            time.sleep(1.2)
            print(f"--- {label}: `{cmdstr}` ---")
        print("======== 汇总输出 ========")
        print(text()[-4000:])
    finally:
        try: p.kill(); p.wait()
        except Exception: pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
