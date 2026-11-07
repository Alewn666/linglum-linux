# 🐧 灵珑系统 · Linux 内核版

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Kernel](https://img.shields.io/badge/Kernel-Linux%207.3.0--rc7-F5C518?logo=linux&logoColor=black)
![Arch](https://img.shields.io/badge/Arch-aarch64-2F855A)
![Release](https://img.shields.io/github/v/release/Alewn666/linglum-linux?label=release)

> 一张能独立启动的 Live ISO：UEFI → GRUB → 自编译 Linux 7.3 内核 → 自研 init（PID 1）→ BusyBox 用户态。开机后屏幕 `tty1` 和串口 `ttyAMA0` 各有一个 shell，直接就是一台能用的 aarch64 系统。

这不是「在某个 Linux 发行版上装几个软件」，而是从内核 `defconfig` 开始自己攒出来的一套操作系统：当前 `build.sh` 直接 `--disable MODULES`，把显示（efidrm / fbcon）、PL011 串口、xHCI + USB HID、virtio 磁盘与网卡全部内建，initramfs 里放自研 `init` 和 BusyBox，最后打成 UEFI 可引导的 ISO。

和 [loongos](https://github.com/Alewn666/loongos) 是同一个「灵珑系统」的两条技术路线：那条连内核一起自己写，这条用 Linux 内核把自己做成一个完整可用的系统。两条路线各自独立，互不替代。

## 启动之后是什么样

```
UEFI → GRUB → Linux 7.3 → 灵珑 Live 环境（tty1 屏幕 + ttyAMA0 串口）
     ├─ 日常使用：shell 里跑任意 busybox 命令（ls / cat / mount / dd / udhcpc …）
     └─ 可选安装：install-loongos /dev/vda
                 → dd 写 MBR + ESP（BOOTAA64.EFI + kernel.elf）
                 → 重启拔盘 → 固件直接加载 ESP → 进入纯自研 LoongOS
```

ISO 里顺手内置了 `install-loongos`（还有 `install-linglum` 与安装向导 `mkinstaller.sh`）：在 Live 环境敲一句，就能把**纯自研内核版**写进目标硬盘。这是附带的安装器，不是本系统唯一的用途。

## 构建：从内核源码到 ISO 全链路可复现

`build.sh` 把整条链路写死了，换台 aarch64 机器照样能编：

```bash
cd 本体
sh build.sh                 # 产物 out/linux.iso
```

它依次做：

1. `make defconfig` 后逐项打开所需特性——EFI / EFI_STUB / ACPI、EFI GOP → efidrm / simpledrm → fbcon、串口控制台、virtio 磁盘与网卡，再用 `--disable MODULES` 关掉模块支持，让它们**全部内建**（`=y`）。
2. 编译内核、准备 `rootfs/`（自研 `init`、`fstab`、`passwd`、`profile`、`motd`、`udhcpc.script`、BusyBox 与 `install-*`）。
3. 打 initramfs、组 ISO、装 GRUB UEFI 引导。

> 脚本里 `-j3` 是特意限的：构建机只有 1.9 GB 内存 + zram，`-j4` 会 OOM。这类「为什么这么写」的细节在脚本注释里都能找到。

## 验收测试

比起「能编出来」，这个项目更在意**真能启动、真能装**：

```bash
cd 本体
python3 test_smoke_boot.py        # 内核启动冒烟
python3 test_linglum_iso.py       # ISO 验收：横幅 / shell / uname / fb0 / 安装器就位
python3 test_linglum_net.py       # 网络（udhcpc / virtio-net）
python3 test_linglum_install.py   # 安装器逻辑
python3 test_install_e2e.py       # 端到端：Live 装 LoongOS → 只挂硬盘重启 → 进 LoongOS
python3 test_wizard_fix.py        # 安装向导回归
```

其中 `test_install_e2e.py` 会真的走完「Live 环境安装 → 拔掉 ISO → 从硬盘启动 → 进入 LoongOS」这条链路，是两条技术路线之间的接口测试。排障脚本 `diag_grub.py`、`diag_mount.py`、`probe_net.py`、`cleanup_qemu.sh` 也一并保留。

## 目录结构

```
linglum-linux/
└── 本体/
    ├── build.sh                 # 内核 → BusyBox → initramfs → ISO 主构建
    ├── init                     # 自研 PID 1
    ├── install-loongos.sh       # 把 LoongOS 写进硬盘
    ├── install-linglum.sh       # 安装本系统
    ├── install/mkinstaller.sh   # 安装向导
    ├── rootfs/                  # 完整用户态骨架（lib/modules 里是早期遗留的 .ko）
    ├── penguin/boot/            # 预编内核 Image.gz
    ├── test_*.py                # 冒烟 / ISO / 网络 / 安装 / 端到端验收
    ├── diag_*.py probe_net.py   # 排障工具
    ├── docs/                    # 检查与修复记录
    └── 说明.md                  # 原始设计说明
```

## 踩过的坑（都写在文档里）

| 现象 | 原因 |
| --- | --- |
| QEMU 串口零输出 | 必须显式 `-drive if=pflash,format=raw,file=/usr/share/AAVMF/AAVMF_CODE.fd`，不是 ISO 坏了 |
| 菜单 / motd 中文变方块 | GRUB 与内核 fbcon 都没有中文字形，所以这两处用英文 |
| `mkdir rootfs/{bin,sbin}` 造出字面量目录 | `/bin/sh` 是 dash，不支持花括号展开 |
| ISO 属主突然变成 `libvirt-qemu` | libvirt 挂载时自动 chown，属正常现象 |
| `rootfs/` 里还有 `.ko` 和 `insmod`，内核却禁用了模块 | 早期 `CONFIG_VIRTIO_NET=m` 版本的遗留：`rootfs/lib/modules/` 下三个 `.ko` 与 `init` 里的 `modprobe` / `insmod` 兜底循环没删干净，**当前构建下不会生效**。构建以 `build.sh` 为准 |

## 说明与边界

- 构建需要 **aarch64 主机**、`aarch64-linux-gnu-` 工具链和完整的 Linux 7.3 内核源码（约 162 MB，解压后 7 GB），内核源码与 >100 MB 的成品 ISO 未纳入仓库，请自备源码后运行 `build.sh`。
- 目标形态是 QEMU / 标准 UEFI aarch64 虚拟机，未适配具体实体板卡。
- 这是实验性自研系统，请勿在生产环境或存有重要数据的磁盘上试安装器。

## 许可证

MIT — 见 [LICENSE](LICENSE)。本项目由 NAS 归档包整理后公开发布。
