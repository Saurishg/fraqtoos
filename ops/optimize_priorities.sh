#!/bin/bash
# Applied on startup via cron @reboot
# Lower priority of non-critical processes

sleep 60  # wait for Chia and other services to start

# Chia — bulk mining processes, yield to everything else
renice 15 $(pgrep chia_full_node)   2>/dev/null
renice 15 $(pgrep chia_wallet)      2>/dev/null
renice 10 $(pgrep chia_harvester)   2>/dev/null
renice 15 $(pgrep -f chia-blockchain) 2>/dev/null

# Desktop — keep GNOME responsive
renice 5  $(pgrep gnome-shell) 2>/dev/null

# AI services — slightly elevated for responsiveness
renice 5  $(pgrep ollama) 2>/dev/null
renice 5  $(pgrep -f "main.py.*8188") 2>/dev/null  # ComfyUI

echo "Process priorities optimized"
