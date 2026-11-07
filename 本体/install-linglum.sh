#!/bin/sh
# ============================================================
#  Linglum self-installer -- install Linglum (Linux) to a disk
#  (ASCII only: the Linux framebuffer console has no CJK glyphs)
#
#  usage:
#    install-linglum                  guided wizard
#    install-linglum /dev/vda         direct, asks for confirmation
#    install-linglum --auto /dev/vda  unattended (tests / batch)
#    install-linglum --list           show installable disks (writes nothing)
#
#  What it writes: a full GPT disk image (ESP with GRUB + ext4 root
#  with kernel/init/busybox). After reboot the firmware loads GRUB
#  from the ESP, GRUB loads the kernel from the ext4 root, the kernel
#  mounts ext4 (built-in driver, no initrd needed) and runs /init.
#  Files in /home then survive reboot.
#
#  The image cannot live on the CD (the kernel has no ISO9660 driver),
#  so it rides in the initramfs as /linglum/linglum.img.gz (gzip) and is
#  streamed straight to the disk with gunzip|dd -- never held in RAM.
# ============================================================
IMG_GZ=${LINGLUM_IMG_GZ:-/linglum/linglum.img.gz}
IMG=${LINGLUM_IMG:-/linglum/linglum.img}
SZ_FILE=/linglum/linglum.img.size
SYS_BLOCK=${LINGLUM_SYS_BLOCK:-/sys/block}   # overridable only for offline tests

E=$(printf '\033')
BOLD="$E[1m"; DIM="$E[2m"; RED="$E[31m"; GRN="$E[32m"; YEL="$E[33m"; CYA="$E[36m"; OFF="$E[0m"

AUTO=0; TARGET=""; LIST=0
for a in "$@"; do
    case "$a" in
        --auto|-y|--yes) AUTO=1 ;;
        --list|-l) LIST=1 ;;
        -*) ;;
        *) TARGET="$a" ;;
    esac
done

# --list is read-only: it must work even when no install image is present
if [ "$LIST" != "1" ]; then
if [ -f "$IMG_GZ" ]; then
    IMG_SRC="gz"
elif [ -f "$IMG" ]; then
    IMG_SRC="raw"
else
    echo "${RED}ERROR: install image missing: $IMG_GZ (or $IMG)${OFF}"; exit 1
fi
fi

clear_screen() { printf '%s[2J%s[H' "$E" "$E"; }
rule() { printf '%s------------------------------------------------------------%s\n' "$DIM" "$OFF"; }
say()  { printf '%s%s%s\n' "$BOLD" "$*" "$OFF"; }

list_disks() {
    # same fix as install-loongos: write to a temp file, NOT subshell vars
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

print_disks() {   # list_disks must have run first; prints /tmp/.linglum_disks with numbers
    i=1
    while IFS='|' read -r d g m; do
        [ -n "$d" ] || continue
        printf '     %s%2d%s)  %-12s %8s   %s\n' "$CYA" "$i" "$OFF" "$d" "$g" "$m"
        i=$((i + 1))
    done < /tmp/.linglum_disks
}

# ---------------- list only (read-only: writes nothing) ----------------
if [ "$LIST" = "1" ]; then
    n=$(list_disks)
    if [ "$n" = "0" ]; then
        echo 'No installable disk found (CD-ROM devices are excluded).'
        exit 1
    fi
    say "Installable disks:"
    echo
    print_disks
    exit 0
fi

show_banner() {
    clear_screen
    printf '%s' "$CYA"
    echo '  +==========================================================+'
    echo '  |         Linglum Installer  -  Linglum (Linux) setup      |'
    echo '  +==========================================================+'
    printf '%s' "$OFF"
}

write_image() {  # $1 = device
    dev=$1
    if [ -z "$dev" ] || [ ! -b "$dev" ]; then
        printf '\n%s   ERROR: target is not a block device: "%s"%s\n' "$RED" "$dev" "$OFF"
        return 1
    fi
    # ---- capacity check: never start writing an image bigger than the disk ----
    # (a too-small disk would end up with a half-written, unbootable GPT)
    need_mb=0
    if [ "$IMG_SRC" = "gz" ]; then
        [ -f "$SZ_FILE" ] && need_mb=$(cat "$SZ_FILE" 2>/dev/null)
    else
        need_mb=$(( ($(wc -c < "$IMG") + 1048575) / 1048576 ))
    fi
    [ "$need_mb" -ge 1 ] 2>/dev/null || need_mb=0
    have=$(cat "$SYS_BLOCK/${dev#/dev/}/size" 2>/dev/null)   # 512-byte sectors
    if [ -n "$have" ] && [ "$need_mb" -ge 1 ]; then
        have_mb=$(( have / 2048 ))
        if [ "$have_mb" -lt "$need_mb" ]; then
            printf '\n%s   ERROR: %s is only %s MB, but the image needs %s MB.%s\n' \
                "$RED" "$dev" "$have_mb" "$need_mb" "$OFF"
            printf '%s         Pick a bigger disk (the image cannot be shrunk).%s\n' "$RED" "$OFF"
            return 1
        fi
    else
        printf '   %s[WARN] could not read %s size; writing anyway.%s\n' "$YEL" "$dev" "$OFF"
    fi
    if [ "$IMG_SRC" = "gz" ]; then
        # streaming: gunzip -> dd, whole image never held in RAM (small-RAM VMs can install)
        # BusyBox gunzip has no -l (list); size is pre-recorded at build time.
        total=200
        [ -f "$SZ_FILE" ] && total=$(cat "$SZ_FILE")
        [ "$total" -ge 1 ] 2>/dev/null || total=200
        echo
        say "   Writing Linglum to $dev ($total MB, streaming from linglum.img.gz) ..."
        echo
        if ! gunzip -c "$IMG_GZ" | dd of="$dev" bs=1048576 conv=notrunc 2>/dev/null; then
            printf '\n%s   ERROR: write failed on %s (disk read-only or broken?).%s\n' "$RED" "$dev" "$OFF"
            return 1
        fi
        printf '\r   [%s%s%s] 100%%\n\n' "$GRN" "################################" "$OFF"
    else
        size=$(wc -c < "$IMG")
        total=$(( size / 1048576 ))
        [ "$total" -lt 1 ] && total=1
        echo
        say "   Writing Linglum to $dev ($total MB) ..."
        echo
        if ! dd if="$IMG" of="$dev" bs=1048576 conv=notrunc 2>/dev/null; then
            printf '\n%s   ERROR: write failed on %s.%s\n' "$RED" "$dev" "$OFF"
            return 1
        fi
        printf '\r   [%s%s%s] 100%%\n\n' "$GRN" "################################" "$OFF"
    fi
    sync
    # GPT protective MBR still carries the 55AA signature -> usable check
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
printf '   %sThis will install Linglum (Linux-based Linglong OS) onto a hard%s\n' "$DIM" "$OFF"
printf '   %sdisk. After reboot, the machine boots Linglum from disk and files%s\n' "$DIM" "$OFF"
printf '   %sin /home survive reboot.%s\n\n' "$DIM" "$OFF"

if [ -n "$TARGET" ]; then
    SELECTED="$TARGET"
    printf '   Target disk (from command line): %s%s%s\n\n' "$BOLD" "$SELECTED" "$OFF"
else
    n=$(list_disks)
    if [ "$n" = "0" ]; then
        printf '   %s[X] No installable disk found.%s\n\n' "$RED" "$OFF"
        echo '   Add a hard disk to this machine/VM, then run install-linglum again.'
        echo '   (CD-ROM devices are excluded automatically)'
        exit 1
    fi
    say "   Available disks:"
    echo
    print_disks
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
printf '   %sInstalls: GPT + GRUB (ESP) + Linglum kernel and root (ext4)%s\n' "$DIM" "$OFF"
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
    echo '     3) power on -- you should see Linglum boot from the disk'
    echo
    printf '   %sNote: /home is on the ext4 root, so files survive reboot.%s\n' "$DIM" "$OFF"
else
    printf '\n   %s[X] Installation failed. Check the disk and retry.%s\n' "$RED" "$OFF"
    exit 1
fi
