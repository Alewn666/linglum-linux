#!/bin/sh
# 精确杀掉持有 ling_e2e_disk.img 写锁的孤儿 QEMU（ppid=1 的那个）
target=188120
if [ -d "/proc/$target" ]; then
  kill -9 "$target" 2>/dev/null && echo "killed $target"
else
  echo "$target already gone"
fi
sleep 1
echo "remaining qemu: $(ps -eo args= | grep qemu-system | grep -v grep | wc -l)"
