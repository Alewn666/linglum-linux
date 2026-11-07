#!/bin/sh
# 灵珑系统 | Linglum Linux —— Linux 内核版构建脚本
# 输入：linux-7.3/（用户提供的完整内核源码）
# 产物：out/linux.iso —— UEFI(GRUB) → 自编译 Linux 7.3 → BusyBox 用户态
# 主机：aarch64（本 NAS），交叉前缀 aarch64-linux-gnu-（同架构原生编译）
set -e
cd "$(dirname "$0")"

ARCH=arm64
CROSS=aarch64-linux-gnu-
SRC=linux-7.3
OUTDIR=out
ISO=$OUTDIR/linux.iso
KVER=$(make -s -C $SRC kernelversion)
JOBS=$(nproc 2>/dev/null || echo 4)
[ "$JOBS" -gt 3 ] && JOBS=3   # 本机 1.9G 内存 + zram，-j4 会 OOM

mkdir -p $OUTDIR build kernel
[ -d $SRC ] || { echo "缺内核源码目录 $SRC"; exit 1; }

echo "== 内核版本：$KVER  并行：$JOBS =="

# ---------- 1. 配置：arm64 defconfig + 灵珑所需特性（全部内建，不要模块） ----------
if [ ! -f build/.config.branded ]; then
    echo "== 生成配置 =="
    make -s -C $SRC ARCH=$ARCH CROSS_COMPILE=$CROSS defconfig
    CFG=$SRC/scripts/config
    # 引导/固件
    $CFG --file $SRC/.config --enable EFI --enable EFI_STUB --enable ACPI --enable EFI_PARTITION
    # 显示：EFI GOP → efidrm/simpledrm → fbcon（Linux 7.3 里 efidrm 是 EFI 帧缓冲正路，
    # 它 depends on !SYSFB_SIMPLEFB，所以不启用 SYSFB_SIMPLEFB）
    $CFG --file $SRC/.config --enable DRM --enable DRM_SIMPLEDRM --enable DRM_EFIDRM --enable FB_EFI \
         --enable FRAMEBUFFER_CONSOLE --enable FRAMEBUFFER_CONSOLE_DETECT_PRIMARY \
         --enable VT --enable VT_CONSOLE --enable FONT_8x16 --enable FONT_TER16x32
    # 串口控制台
    $CFG --file $SRC/.config --enable SERIAL_AMBA_PL011 --enable SERIAL_AMBA_PL011_CONSOLE
    # 输入：xHCI + USB HID（虚拟机 usb-kbd / 真机键盘鼠标）
    $CFG --file $SRC/.config --enable USB_SUPPORT --enable USB --enable USB_XHCI_HCD \
         --enable USB_XHCI_PCI --enable USB_HID --enable HID --enable HID_GENERIC
    # virtio（虚拟机磁盘/网卡，阶段 6 持久化用）
    $CFG --file $SRC/.config --enable PCI --enable VIRTIO --enable VIRTIO_PCI \
         --enable VIRTIO_MMIO --enable VIRTIO_BLK --enable VIRTIO_NET
    # initramfs + 基础文件系统
    $CFG --file $SRC/.config --enable BLK_DEV_INITRD --enable RD_GZIP \
         --enable DEVTMPFS --enable DEVTMPFS_MOUNT --enable PROC_FS --enable SYSFS --enable TMPFS
    # 不要模块：需要的东西全内建，构建更快、initramfs 更简单
    $CFG --file $SRC/.config --disable MODULES
    # 关掉不需要的大件，缩小编译时间
    $CFG --file $SRC/.config --disable NET_VENDOR_ALL --disable WLAN --disable SOUND 2>/dev/null || true
    make -s -C $SRC ARCH=$ARCH CROSS_COMPILE=$CROSS olddefconfig
    cp $SRC/.config build/.config.branded
else
    cp build/.config.branded $SRC/.config
    make -s -C $SRC ARCH=$ARCH CROSS_COMPILE=$CROSS olddefconfig
fi

# ---------- 2. 内核 Image：优先用预编内核（用户提供的清华版 aarch64 包） ----------
if [ -f penguin/boot/Image ]; then
    echo "== 使用预编内核 penguin/boot/Image（7.3.0-rc7-aarch64，跳过编译）=="
    cp penguin/boot/Image kernel/Image
elif [ ! -f $SRC/arch/$ARCH/boot/Image ] || [ "$(cat build/kver.stamp 2>/dev/null)" != "$KVER" ]; then
    echo "== 编译内核（首次约 10~30 分钟）=="
    make -C $SRC ARCH=$ARCH CROSS_COMPILE=$CROSS -j$JOBS Image
    echo "$KVER" > build/kver.stamp
    cp $SRC/arch/$ARCH/boot/Image kernel/Image
else
    cp $SRC/arch/$ARCH/boot/Image kernel/Image
fi
ls -la kernel/Image

# ---------- 3. BusyBox 用户态（静态二进制） ----------
mkdir -p debs
if ! ls debs/busybox-static_*.deb >/dev/null 2>&1; then
    echo "== 下载 busybox-static =="
    ( cd debs && apt-get download busybox-static >/dev/null 2>&1 )
fi
rm -rf build/bdeb && mkdir -p build/bdeb && dpkg-deb -x debs/busybox-static_*.deb build/bdeb
mkdir -p rootfs/bin
cp -a build/bdeb/bin/busybox rootfs/bin/busybox
chmod +x rootfs/bin/busybox rootfs/init rootfs/etc/udhcpc.script

# ---------- 3.5 安装素材 + 安装器 ----------
# 两套安装盘并存：
#   LoongOS  = 纯自研内核（install-loongos → install/disk.img.gz）
#   Linglum  = Linux 内核版（install-linglum → install/linglum.img.gz，自装到 ext4 根）
# 预编内核没有 ISO9660，光盘挂不上，镜像只能随 initramfs 走；
# 压缩存放 + 安装时 zcat|dd 流式写盘，大镜像全程不进内存。
if [ -f install/disk.img ]; then
    echo "== LoongOS 安装素材（压缩进 initramfs）=="
    mkdir -p rootfs/loongos
    gzip -9 -c install/disk.img > rootfs/loongos/disk.img.gz
    echo $(( $(wc -c < install/disk.img) / 1048576 )) > rootfs/loongos/disk.img.size
    ls -la rootfs/loongos/disk.img.gz rootfs/loongos/disk.img.size
fi
cp install-loongos.sh rootfs/bin/install-loongos
chmod +x rootfs/bin/install-loongos

# ---- Linglum 自装镜像：宿主预制 GPT+ESP+ext4，压缩进 initramfs ----
echo "== Linglum 自装素材（宿主预制 → 压缩进 initramfs）=="
sh install/mkinstaller.sh
mkdir -p rootfs/linglum
cp install/linglum.img.gz   rootfs/linglum/linglum.img.gz
cp install/linglum.img.size rootfs/linglum/linglum.img.size
cp install-linglum.sh rootfs/bin/install-linglum
chmod +x rootfs/bin/install-linglum
ls -la rootfs/linglum/linglum.img.gz rootfs/linglum/linglum.img.size rootfs/bin/install-linglum

# ---------- 4. initramfs ----------
echo "== 打包 initramfs =="
( cd rootfs && find . -print0 | cpio --null -o --format=newc 2>/dev/null | gzip -9 ) > build/initrd.img
ls -la build/initrd.img

# ---------- 5. ISO ----------
echo "== 组装 ISO =="
rm -rf build/iso && mkdir -p build/iso/boot/grub
cp kernel/Image build/iso/boot/Image
cp build/initrd.img build/iso/boot/initrd.img

cat > build/iso/boot/grub/grub.cfg <<'EOF'
set timeout=0
set default=0
menuentry 'Linglum Linux 7.3 Live Installer' {
    linux /boot/Image console=ttyAMA0 console=tty0 loglevel=4
    initrd /boot/initrd.img
}
EOF
grub-mkrescue -o $ISO build/iso -volid LINGLONG >/dev/null 2>&1
echo "✅ 完成：$ISO （$(stat -c %s $ISO) 字节）"
