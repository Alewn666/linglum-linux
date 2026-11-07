#!/bin/sh
for p in $(ps -eo pid=,args= | grep 'qemu-system' | grep -v grep | grep -E 'le2e|grubdbg' | awk '{print $1}'); do
  sudo -n kill -9 "$p" 2>/dev/null && echo "killed $p"
done
sleep 1
echo "remaining: $(ps -eo args= | grep 'qemu-system' | grep -v grep | grep -cE 'le2e|grubdbg')"
