#!/usr/bin/env python3
"""网络验收：Linglum Live 与装盘后都能 DHCP 拿到 IP 并 ping 通网关（2026-10-29 网络支持）

阶段 A：Live（只挂网卡）→ 启动后 [net] 行拿到 SLIRP IP → ping 10.0.2.2
阶段 B：空白盘 install-linglum /dev/vda → 确认写入 → poweroff
阶段 C：只挂硬盘 + 网卡 → 同样 DHCP 拿 IP + ping 通

用法：python3 test_linglum_net.py [--kvm]   （KVM 必开，TCG 下装盘会超时）
复用 test_linglum_install 的 VM 骨架与 AAVMF 旗标。
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_linglum_install as base  # noqa: E402  （模块级读 sys.argv → --kvm 一并生效）

NETDEV = ["-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0"]


def main():
    if not os.path.exists(base.ISO):
        print("缺 ISO:", base.ISO)
        return 1
    ok = []
    disk_arg = ["-drive", f"if=none,id=d0,format=raw,file={base.DISK}",
                "-device", "virtio-blk-pci,drive=d0"]
    ip_pat = r"inet addr:10\.0\.2\."
    ping_pat = r"2 packets transmitted, 2 received, 0% packet loss"

    print("=== 阶段 A：Live + 网卡 → DHCP 拿 IP + ping ===")
    vm = base.VM(["-cdrom", base.ISO] + NETDEV, "na")
    try:
        if not vm.wait(r"Linglum Linux[\s\S]*#", 260, "Live 环境就绪"):
            print("---- 串口尾部 ----"); print(vm.text()[-2000:]); return 1
        ok.append(True)
        if not vm.wait(ip_pat, 30, "拿到 SLIRP IP 10.0.2.x"):
            print("---- 串口尾部 ----"); print(vm.text()[-2500:]); return 1
        ok.append(True)
        vm.send("ping -c 2 10.0.2.2")
        if not vm.wait(ping_pat, 30, "ping 通网关 10.0.2.2（2/2 收包）"):
            print("---- 串口尾部 ----"); print(vm.text()[-2500:]); return 1
        ok.append(True)
        time.sleep(1)
    finally:
        vm.kill()

    print("=== 阶段 B：Live 盘内安装 Linglum（带网卡）===")
    subprocess.run(["rm", "-f", base.DISK])
    subprocess.run(["truncate", "-s", "512M", base.DISK], check=True)
    vm = base.VM(["-cdrom", base.ISO] + NETDEV + disk_arg, "nb")
    try:
        if not vm.wait(r"Linglum Linux[\s\S]*#", 260, "Live 环境就绪"):
            print("---- 串口尾部 ----"); print(vm.text()[-2000:]); return 1
        ok.append(True)
        vm.send("install-linglum /dev/vda")
        if not vm.wait(r"to confirm", 20, "安装器确认提示"):
            print("---- 串口尾部 ----"); print(vm.text()[-2000:]); return 1
        ok.append(True)
        vm.send("yes")
        if not vm.wait(r"Installation complete|DONE: installed", 600, "Linglum 写入完成"):
            print("---- 串口尾部 ----"); print(vm.text()[-2500:]); return 1
        ok.append(True)
        time.sleep(1)
        vm.send("poweroff -f")
        time.sleep(4)
    finally:
        vm.kill()

    print("=== 阶段 C：只挂硬盘 + 网卡 → DHCP 拿 IP + ping ===")
    vm = base.VM(disk_arg + NETDEV, "nc")
    try:
        if not vm.wait(r"Linglum Linux[\s\S]*#", 180, "从硬盘进入 Linglum"):
            print("---- 串口尾部 ----"); print(vm.text()[-2500:]); return 1
        ok.append(True)
        if not vm.wait(ip_pat, 30, "硬盘系统也拿到 IP"):
            print("---- 串口尾部 ----"); print(vm.text()[-2500:]); return 1
        ok.append(True)
        vm.send("ping -c 2 10.0.2.2")
        if not vm.wait(ping_pat, 30, "硬盘系统 ping 通网关（2/2 收包）"):
            print("---- 串口尾部 ----"); print(vm.text()[-2500:]); return 1
        ok.append(True)
        time.sleep(1)
    finally:
        vm.kill()

    print(f"\n== {'ALL PASS' if all(ok) else 'FAIL'} （{sum(ok)}/{len(ok)}）==")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
