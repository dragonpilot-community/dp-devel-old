#!/usr/bin/bash

export LD_LIBRARY_PATH=/data/data/com.termux/files/usr/lib
export HOME=/data/data/com.termux/files/home
export PATH=/usr/local/bin:/data/data/com.termux/files/usr/bin:/data/data/com.termux/files/usr/sbin:/data/data/com.termux/files/usr/bin/applets:/bin:/sbin:/vendor/bin:/system/sbin:/system/bin:/system/xbin:/data/data/com.termux/files/usr/bin/git
export PYTHONPATH=/data/openpilot
echo -n 1 > /data/params/d/dp_is_updating
rm /data/openpilot/panda/board/obj/panda.bin
cd /data/openpilot && git fetch --all && git reset --hard @{u} && git clean -xdf && scons --clean && reboot
