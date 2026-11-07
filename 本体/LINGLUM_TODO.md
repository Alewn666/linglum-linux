# LINGLUM — 让 Linglum 把自己装进硬盘（持久化，不依赖自研内核驱动）

## 背景
Linglum 现在只有 Live 形态（rootfs 在内存 initramfs，断电清零）。
目标：`install-linglum` 命令把 Linglum 本身装进硬盘，装完不插光盘也能启动、`/home` 重启不丢。

## 关键设计（已验证）
- 内核 IKCONFIG 证实 `CONFIG_EXT4_FS=y`（ext4 内建）、`CONFIG_VFAT_FS=y`、`CONFIG_BLK_DEV_SD=y`、
  `CONFIG_VIRTIO_BLK=y`、`CONFIG_EFI_STUB=y`、`CONFIG_BLK_DEV_INITRD=y` + `CONFIG_RD_GZIP=y`
  → 内核可直接挂 ext4 根分区（root=PARTUUID），**不需要额外 initramfs**
- 宿主工具链（**纯文件操作，不需要 loop 设备 / root**）：
  `grub-mkstandalone`（产 arm64 EFI）+ `mkfs.vfat --offset` + `mke2fs -d`（从目录填 ext4）+ `mmd`/`mcopy`
- 内核 Image 51MB（gzip 18MB）→ 塞进 Live initramfs 作为装机材料（22MB gz，512MB VM 够用）

## 步骤
- [x] 前置能力验证：ext4 内建 / GRUB EFI / 纯文件造镜像
- [x] 1. 写 `install-linglum.sh`（Live 里的装机命令，同 install-loongos 风格）
- [x] 2. 写 `install/mkinstaller.sh`（宿主预制 linglum.img.gz：GPT + ESP + ext4 + grub.cfg）
      —— 已跑通：194MB raw → 23MB gz；ESP 有 GRUB EFI，ext4 有 kernel/init/busybox
- [x] 3. 改 `build.sh`：接 mkinstaller，装机镜像+命令进 initramfs
- [x] 4. 改 `init`：双模式（Live=tmpfs / 装机=ext4），同一脚本服务两者
- [x] 5. 重建 ISO
- [x] 6. 端到端验证：Live 装机 → 只挂硬盘重启进 Linglum → 写 /home 文件 → 再重启文件还在
      （KVM `test_linglum_install.py --kvm` **9/9 ALL PASS**，见 docs 第 2 轮）
- [x] 7. 同步 NAS：✅ ISO 已同步（2026-10-27，`linux.iso` = `6676f78d…`）；
      ✅ 项目文件目录 `/vol1/1000/项目/Linglum/` **已核实同步完成**（2026-10-27 07:2x 对账：
      17 个源文件 + `install/`、`docs/` 子目录全部 md5 一致，0 缺失 0 差异；
      ISO 两边同为 `6676f78d37544b58c2bb9ea8daa42f77`）
      —— 本条原写"仍是 10-25 旧版"为**过时记录**，实际早已同步，已订正

## 红线（沿用）
- 测试用 TCG `-m 320 -smp 1`（内存）；ISO 用 build/ 下的，别动 NAS 上用户正在挂的
- 每步改完立即验证；未验证不写"完成"

## 8. 安装器写盘前容量校验 + `--list` 选项（2026-10-27 第 4 轮，每小时定时小件）
- [x] 8.1 `install-linglum.sh`：写盘前比对目标盘容量 vs 镜像大小，太小直接拒绝（现在会写到一半留下半截坏盘）
- [x] 8.2 `install-linglum.sh`：新增 `--list`（只列可装磁盘，不写任何东西）
- [x] 8.3 离线验证：busybox `sh -n` 语法 + 假 sysfs 下容量校验逻辑实测（小盘拒绝 / 大盘放行 / 读不到容量只警告不拦）
- [x] 8.4 重建 ISO（新 install-linglum 已打进 initramfs）+ 同步 NAS —— 2026-10-27 第 5 轮：
      `sh build.sh` EXIT=0，新 ISO `a5cba9de0e1e5699456f3b30e65b7934`（旧 `6676f78d…` 备份在 `build/linux.iso.bak_r4` 与 NAS 同目录 `.bak_r5_20261027`）；
      xorriso 拆包核实：`/boot/initrd.img` 里 `bin/install-linglum` md5 = `6d41811e…`（= 带容量校验+--list 的新版）；`/boot/Image` md5 `70f3135d…` 与旧 ISO 逐字节相同（内核没动）；
      顺带修好 NAS 归档 `Linglum/rootfs/`：`bin/install-loongos` 原是 **0 字节坏文件**、`bin/install-linglum` 缺失、`init` 是 10-25 旧版 → 已全部对齐工作区（8 个文件 md5 全 SAME）；
      KVM e2e（装机→只挂盘启动→持久化）仍需用户实测或下一轮起 VM（遵守「不在 NAS 上起测试虚拟机」红线）
