#!/bin/sh
# ============================================================
#  mkinstaller.sh -- build the Linglum self-install disk image
#  (host-side; run from linglong-linux/ root)
#
#  Produces: install/linglum.img.gz (+ install/linglum.img.size)
#
#  Layout (GPT):
#    p1 ESP   FAT32  64 MB  -- GRUB EFI only (grub.cfg embedded)
#    p2 root  ext4  128 MB  -- /boot/Image (kernel) + /init + busybox + /etc
#
#  GRUB loads the kernel from the ext4 root (root=PARTUUID, fixed GUID),
#  kernel mounts ext4 (built-in driver) and runs /init. No initrd needed.
#
#  All operations are plain file I/O -- no loop devices, no root.
#    ESP  : mkfs.vfat + mmd/mcopy on the standalone FAT file
#    root : mke2fs -d (populate ext4 from a directory)
#    then sfdisk GPT + dd the two fs files into place.
# ============================================================
set -e
cd "$(dirname "$0")/.."          # linglong-linux/

KERNEL=penguin/boot/Image
INITRD_SRC=rootfs/init            # init script (reused verbatim)
BUSYBOX=rootfs/bin/busybox
OUT_DIR=install
IMG=$OUT_DIR/linglum.img
IMG_GZ=$OUT_DIR/linglum.img.gz

# ---- fixed partition GUIDs (must match grub.cfg + kernel cmdline) ----
ESP_GUID="00000000-0000-4000-8000-000000000001"
ROOT_GUID="11111111-2222-3333-4444-555555555555"

# ---- geometry (sectors of 512) ----
ESP_START=2048
ESP_SIZE=131072          # 64 MB
ROOT_START=$((ESP_START + ESP_SIZE))   # 133120
ROOT_SIZE=262144         # 128 MB
# GPT needs ~33 sectors at the END for the backup header+entries; leave slack
TOTAL_SECTORS=$((ROOT_START + ROOT_SIZE + 2048))
TOTAL_MB=$((TOTAL_SECTORS * 512 / 1048576))

WORK=build/mkinstall
rm -rf "$WORK"
mkdir -p "$WORK" "$OUT_DIR"

echo "== [1/6] stage installed rootfs =="
STAGE=$WORK/root
mkdir -p "$STAGE"
# base tree (dirs + etc) from rootfs, minus the Live-only install images
cp -a rootfs/. "$STAGE"/
rm -rf "$STAGE/loongos" "$STAGE/linglum"     # install media ride in Live initramfs only
mkdir -p "$STAGE/boot"
cp "$KERNEL" "$STAGE/boot/Image"             # kernel lives on the ext4 root
chmod 755 "$STAGE/boot/Image" "$STAGE/init" "$STAGE/bin/busybox"
echo "   staged: $(du -sh "$STAGE" | cut -f1) (incl. kernel)"

echo "== [2/6] build GRUB EFI (arm64, embedded grub.cfg) =="
GRUB_CFG=$WORK/grub.cfg
cat > "$GRUB_CFG" <<EOF
set timeout=3
set default=0
search --no-floppy --set=root --label linglum
menuentry "Linglum" {
    linux /boot/Image root=PARTUUID=$ROOT_GUID init=/init rw console=ttyAMA0 console=tty0 loglevel=4
}
EOF
grub-mkstandalone --format=arm64-efi \
    --modules="part_gpt fat ext2 linux normal configfile search search_fs_uuid search_label search_fs_file" \
    -o "$WORK/BOOTAA64.EFI" "boot/grub/grub.cfg=$GRUB_CFG"
echo "   BOOTAA64.EFI: $(du -h "$WORK/BOOTAA64.EFI" | cut -f1)"

echo "== [3/6] build ext4 root partition (mke2fs -d) =="
ROOT_FS=$WORK/root.ext4
truncate -s $((ROOT_SIZE * 512)) "$ROOT_FS"
mke2fs -q -F -t ext4 -L linglum -d "$STAGE" "$ROOT_FS"
echo "   root.ext4: $(du -h "$ROOT_FS" | cut -f1)"

echo "== [4/6] build ESP (FAT32 + GRUB EFI) =="
ESP_FS=$WORK/esp.img
truncate -s $((ESP_SIZE * 512)) "$ESP_FS"
mkfs.vfat -F 32 -n ESP "$ESP_FS" >/dev/null
mmd -i "$ESP_FS" ::/EFI ::/EFI/BOOT
mcopy -i "$ESP_FS" "$WORK/BOOTAA64.EFI" ::/EFI/BOOT/BOOTAA64.EFI
echo "   esp.img: $(du -h "$ESP_FS" | cut -f1)"

echo "== [5/6] assemble GPT disk image =="
rm -f "$IMG"
truncate -s $((TOTAL_SECTORS * 512)) "$IMG"
sfdisk -q "$IMG" <<EOF
label: gpt
unit: sectors
start=$ESP_START,  size=$ESP_SIZE,  type=U, uuid=$ESP_GUID
start=$ROOT_START, size=$ROOT_SIZE, type=L, uuid=$ROOT_GUID
EOF
dd if="$ESP_FS"  of="$IMG" bs=512 seek=$ESP_START  conv=notrunc status=none
dd if="$ROOT_FS" of="$IMG" bs=512 seek=$ROOT_START conv=notrunc status=none
echo "   img: $TOTAL_MB MB"

echo "== [6/6] compress =="
gzip -9 -n -c "$IMG" > "$IMG_GZ"
echo "$TOTAL_MB" > "$OUT_DIR/linglum.img.size"
GZ_SZ=$(du -h "$IMG_GZ" | cut -f1)
echo "   $IMG_GZ  ($GZ_SZ gz, $TOTAL_MB MB raw)"

# ---- verify the assembled image ----
echo "== verify =="
sfdisk -l "$IMG" 2>/dev/null | grep -E 'Disk|Device|img1|img2' || true
# check 55AA protective-MBR signature
sig=$(dd if="$IMG" bs=1 skip=510 count=2 2>/dev/null | od -An -tx1 | tr -d ' \n')
[ "$sig" = "55aa" ] && echo "   MBR sig 55AA OK" || { echo "   MBR sig BAD ($sig)"; exit 1; }
echo "OK: $IMG_GZ"
