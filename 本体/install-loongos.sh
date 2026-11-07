#!/bin/sh
# ============================================================
#  Linglum Installer -- install LoongOS to a disk
#  (ASCII only: the Linux framebuffer console has no CJK glyphs)
#
#  usage:
#    install-loongos                  guided wizard
#    install-loongos /dev/vdb         direct, asks for confirmation
#    install-loongos --auto /dev/vdb  unattended (tests / batch)
# ============================================================
# 镜像来源（2026-10-25）：内核不带 ISO9660，镜像只能随 initramfs 走。
# 为省内存，initramfs 里放的是 disk.img.gz（0.2MB），安装时 zcat 流式写盘。
IMG_GZ=${LOONGOS_IMG_GZ:-/loongos/disk.img.gz}
IMG=${LOONGOS_IMG:-/loongos/disk.img}
E=$(printf '\033')
BOLD="$E[1m"; DIM="$E[2m"; RED="$E[31m"; GRN="$E[32m"; YEL="$E[33m"; CYA="$E[36m"; OFF="$E[0m"

AUTO=0; TARGET=""
for a in "$@"; do
    case "$a" in
        --auto|-y|--yes) AUTO=1 ;;
        -*) ;;
        *) TARGET="$a" ;;
    esac
done

if [ -f "$IMG_GZ" ]; then
    IMG_SRC="gz"
elif [ -f "$IMG" ]; then
    IMG_SRC="raw"
else
    echo "${RED}ERROR: install image missing: $IMG_GZ (or $IMG)${OFF}"; exit 1
fi

clear_screen() { printf '%s[2J%s[H' "$E" "$E"; }
rule() { printf '%s------------------------------------------------------------%s\n' "$DIM" "$OFF"; }
say()  { printf '%s%s%s\n' "$BOLD" "$*" "$OFF"; }

list_disks() {
    # ⚠️ 2026-10-25 修复：原实现用 eval "DISK_$n=..." 存列表，但本函数是在
    #    `n=$(list_disks)` 的**子 shell** 里执行的 —— 变量出了子 shell 全丢，
    #    父 shell 拿到空名字/空容量 → dd of="" → "write failed at block 0"（真机踩到）。
    #    现在把结果写到临时文件，父 shell 读文件，不依赖子 shell 变量。
    n=0
    : > /tmp/.linglum_disks
    for d in /sys/block/vd* /sys/block/sd* /sys/block/nvme*; do
        [ -e "$d" ] || continue
        name=${d##*/}
        [ "$(cat "$d/ro" 2>/dev/null)" = "1" ] && continue      # skip cdrom / read-only
        [ -b "/dev/$name" ] || continue
        sec=$(cat "$d/size" 2>/dev/null || echo 0)
        gb=$(( sec / 2097152 ))
        if [ "$gb" -ge 1 ]; then sz="$gb GB"; else sz="$(( sec / 2048 )) MB"; fi
        model=$(cat "$d/device/model" 2>/dev/null | tr -d '\n' | sed 's/  */ /g')
        n=$((n + 1))
        printf '%s|%s|%s\n' "/dev/$name" "$sz" "$model" >> /tmp/.linglum_disks
    done
    echo "$n"
}

show_banner() {
    clear_screen
    printf '%s' "$CYA"
    echo '  +==========================================================+'
    echo '  |        Linglum Installer  -  LoongOS setup               |'
    echo '  +==========================================================+'
    printf '%s' "$OFF"
}

progress_bar() {  # $1 done, $2 total
    # ⚠️ 变量名必须以 pb_ 开头：POSIX sh 没有局部变量，
    #    早先用 i 把 write_image 的循环计数器冲掉，导致进度卡 50% 无限循环（2026-10-25 实测抓到）
    pb_i=0; pb_bar=""
    while [ $pb_i -lt 32 ]; do
        if [ $((pb_i * $2 / 32)) -lt "$1" ]; then pb_bar="$pb_bar#"; else pb_bar="$pb_bar."; fi
        pb_i=$((pb_i + 1))
    done
    pb_pct=$(( $1 * 100 / $2 ))
    printf '\r   [%s%s%s] %3d%%' "$GRN" "$pb_bar" "$OFF" "$pb_pct"
}

write_image() {  # $1 = device
    dev=$1
    if [ -z "$dev" ] || [ ! -b "$dev" ]; then
        printf '\n%s   ERROR: target is not a block device: "%s"%s\n' "$RED" "$dev" "$OFF"
        return 1
    fi
    if [ "$IMG_SRC" = "gz" ]; then
        # 流式：gunzip → dd，129MB 全程不进内存（小内存虚拟机也能装）
        # ⚠️ BusyBox 的 gunzip 没有 -l（list），只有 -c/-f/-k/-t —— 别用 -l 算大小（2026-10-25 真机踩到）
        # 解压后大小固定（disk.img = 129MB），构建时写进 /loongos/disk.img.size
        total=129
        [ -f /loongos/disk.img.size ] && total=$(cat /loongos/disk.img.size)
        [ "$total" -ge 1 ] 2>/dev/null || total=129
        echo
        say "   Writing LoongOS to $dev ($total MB, streaming from disk.img.gz) ..."
        echo
        if ! gunzip -c "$IMG_GZ" | dd of="$dev" bs=1048576 conv=notrunc 2>/dev/null; then
            printf '\n%s   ERROR: write failed on %s (disk read-only or broken?).%s\n' "$RED" "$dev" "$OFF"
            return 1
        fi
        printf '\r   [%s%s%s] 100%%\n\n' "$GRN" "################################" "$OFF"
        sync
        sig=$(dd if="$dev" bs=1 skip=510 count=2 2>/dev/null | od -An -tx1 | tr -d ' \n')
        if [ "$sig" = "55aa" ]; then
            printf '   %s[OK] partition table verified (MBR signature 55AA)%s\n' "$GRN" "$OFF"
            return 0
        fi
        printf '   %s[WARN] MBR signature read back as "%s" -- please retry.%s\n' "$YEL" "${sig:-none}" "$OFF"
        return 1
    fi
    size=$(wc -c < "$IMG")
    total=$(( size / 1048576 ))
    [ "$total" -lt 1 ] && total=1
    echo
    say "   Writing LoongOS to $dev ($total MB) ..."
    echo
    i=0
    while [ $i -lt "$total" ]; do
        if ! dd if="$IMG" of="$dev" bs=1048576 skip=$i seek=$i count=1 conv=notrunc 2>/dev/null; then
            printf '\n%s   ERROR: write failed at block %d (disk read-only or broken?).%s\n' "$RED" "$i" "$OFF"
            return 1
        fi
        i=$((i + 1))
        progress_bar $i $total
    done
    printf '\n\n'
    sync
    sig=$(dd if="$dev" bs=1 skip=510 count=2 2>/dev/null | od -An -tx1 | tr -d ' \n')
    if [ "$sig" = "55aa" ]; then
        printf '   %s[OK] partition table verified (MBR signature 55AA)%s\n' "$GRN" "$OFF"
        return 0
    fi
    printf '   %s[WARN] MBR signature read back as "%s" -- please retry.%s\n' "$YEL" "${sig:-none}" "$OFF"
    return 1
}

# ---------------- unattended ----------------
if [ "$AUTO" = "1" ]; then
    [ -b "$TARGET" ] || { echo "invalid target: $TARGET"; exit 1; }
    write_image "$TARGET" || exit 1
    echo "DONE: installed to $TARGET"
    exit 0
fi

# ---------------- guided wizard ----------------
show_banner
printf '   %sThis will install Linglum OS (LoongOS, self-developed kernel)%s\n' "$DIM" "$OFF"
printf '   %sonto a hard disk. After reboot, the machine boots LoongOS.%s\n\n' "$DIM" "$OFF"

if [ -n "$TARGET" ]; then
    SELECTED="$TARGET"
    printf '   Target disk (from command line): %s%s%s\n\n' "$BOLD" "$SELECTED" "$OFF"
else
    n=$(list_disks)
    if [ "$n" = "0" ]; then
        printf '   %s[X] No installable disk found.%s\n\n' "$RED" "$OFF"
        echo '   Add a hard disk to this machine/VM, then run install-loongos again.'
        echo '   (CD-ROM devices are excluded automatically)'
        exit 1
    fi
    say "   Available disks:"
    echo
    i=1
    while IFS='|' read -r d g m; do
        [ -n "$d" ] || continue
        printf '     %s%2d%s)  %-12s %8s   %s\n' "$CYA" "$i" "$OFF" "$d" "$g" "$m"
        i=$((i + 1))
    done < /tmp/.linglum_disks
    echo
    printf '   Choose disk [1-%d], Enter = 1 : ' "$n"
    read sel
    [ -z "$sel" ] && sel=1
    case "$sel" in
        ''|*[!0-9]*) printf '\n%s[X] invalid input%s\n' "$RED" "$OFF"; exit 1 ;;
    esac
    if [ "$sel" -lt 1 ] || [ "$sel" -gt "$n" ]; then
        printf '\n%s[X] number out of range%s\n' "$RED" "$OFF"; exit 1
    fi
    SELECTED=$(sed -n "${sel}p" /tmp/.linglum_disks | cut -d'|' -f1)
    [ -n "$SELECTED" ] || { printf '\n%s[X] cannot resolve disk %s%s\n' "$RED" "$sel" "$OFF"; exit 1; }
fi

echo
rule
printf '   Target : %s%s%s\n' "$BOLD" "$GRN" "$SELECTED" "$OFF"
printf '   %sWARNING: ALL DATA on this disk will be erased. This cannot be undone.%s\n' "$RED" "$OFF"
printf '   %sInstalls: LoongOS bootloader + kernel into an EFI system partition%s\n' "$DIM" "$OFF"
rule
printf '   Type %syes%s to confirm (anything else cancels): ' "$BOLD" "$OFF"
read ans
if [ "$ans" != "yes" ]; then
    echo
    echo '   Cancelled. Nothing was written.'
    exit 1
fi

if write_image "$SELECTED"; then
    show_banner
    printf '   %s[OK] Installation complete.%s\n\n' "$GRN" "$OFF"
    echo '   Next steps:'
    printf '     1) shutdown:  %spoweroff -f%s\n' "$BOLD" "$OFF"
    echo '     2) remove the installer disc (or change boot order)'
    echo '     3) power on -- you should see Linglum / LoongOS banner'
    echo
    printf '   %sNote: files in /home now survive reboot (disk persistence, stage 6).%s\n' "$DIM" "$OFF"
else
    printf '\n   %s[X] Installation failed. Check the disk and retry.%s\n' "$RED" "$OFF"
    exit 1
fi
