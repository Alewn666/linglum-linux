# LINGLUM — 灵珑系统（Linux 内核版）

> 定位（2026-10-25 用户确认）：Linglum **本身就是一个独立的 Linux 操作系统**
> （自有内核 + 自有 init(PID1) + BusyBox 用户态），`install-loongos` 只是它系统里的一个普通程序。
> 本目录 = 开发源；NAS 归档 = `/vol1/1000/项目/Linglum/`；成品 ISO = `/vol1/1000/项目/loongos/iso/Linux内核ISO/linux.iso`

## 已完成
- [x] 1. 源码确认 + 预编内核 7.3.0-rc7 aarch64（penguin/boot/Image，驱动全内建）
- [x] 2. Live 环境跑通（QEMU 必须显式 `-drive if=pflash` 加载 AAVMF）
- [x] 3. 安装素材 `install/disk.img`（p1 ESP + p2 数据区 0x99）
- [x] 4. `install-loongos`（dd 写盘，不依赖 mkfs；向导 bug 已修）
- [x] 5. ISO 打包（grub-mkrescue，ASCII 菜单）
- [x] 6. 端到端 7/7：Live 安装 LoongOS → 只挂硬盘重启 → 进 LoongOS
- [x] 7. 内存/光盘双坑修复：disk.img 压缩 0.2MB 进 initramfs + `gunzip | dd` 流式写盘

## 本轮（第 5 轮）：自己装进硬盘 —— 从 Live 变成可持久使用的系统
- [ ] 5.1 探明内核运行时能力：ext4 / vfat 是否内建、busybox 有无 switch_root
- [ ] 5.2 设计安装布局：p1 ESP(FAT32, GRUB+Image+initrd) + p2 ext4(rootfs + /home)
- [ ] 5.3 `tools/make_system_img.sh`：宿主机生成 system.img（含 GRUB standalone EFI）
- [ ] 5.4 `init` 支持装盘模式：扫描带标记的根分区 → mount → switch_root；无则回 Live
- [ ] 5.5 `install-linglum` 安装器（压缩镜像流式写盘 + 向导/--auto）
- [ ] 5.6 build.sh 接入 + 重打 ISO
- [ ] 5.7 E2E：Live 安装 → 拔盘重启进灵珑 → 写 /home 文件 → 再重启仍在
- [ ] 5.8 同步 NAS + md5 对账 + 检查与修复记录

## 已知坑
- QEMU 不带 pflash → UEFI 固件不加载 → 串口零输出（不是 ISO 坏）
- GRUB 字体无中文 → 菜单标题用 ASCII；内核 fbcon 也无 CJK
- `/bin/sh` 是 dash，**不支持 `{}` 花括号展开**
- 预编内核无 ISO9660/UDF/BLK_DEV_SR → 光盘挂不上，安装素材只能随 initramfs 走
- 大块数据永远压缩 + 流式写盘，别进 RAM
