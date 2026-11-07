#!/usr/bin/env python3
"""网络探针（一次性诊断）：Live 里查 modprobe/模块/PCI 现场，定位“没有发现网卡”。

用法：python3 -u probe_net.py [--kvm]
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
if "--kvm" not in sys.argv:
    sys.argv.append("--kvm")
import test_linglum_install as b  # noqa: E402


def main():
    netdev = ["-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0"]
    vm = b.VM(["-cdrom", b.ISO] + netdev, "pn")
    try:
        if not vm.wait(r"Linglum Linux[\s\S]*#", 260, "Live 就绪"):
            print(vm.text()[-1500:])
            return 1
        cmds = [
            ("uname -r", 1.5),
            ("modprobe virtio_net; echo MODRC=$?", 2.5),
            ("insmod /lib/modules/*/kernel/net/core/failover.ko; echo R1=$?", 2.0),
            ("lsmod", 1.5),
            ("insmod /lib/modules/*/kernel/drivers/net/net_failover.ko; echo R2=$?", 2.0),
            ("lsmod", 1.5),
            ("insmod /lib/modules/*/kernel/drivers/net/virtio_net.ko; echo R3=$?", 2.5),
            ("ls /sys/class/net; lsmod", 2.0),
            ("dmesg | tail -12", 1.5),
        ]
        for c, s in cmds:
            print(">>> " + c)
            vm.send(c)
            time.sleep(s)
        print("======== 串口尾部 ========")
        print(vm.text()[-5000:])
    finally:
        vm.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
