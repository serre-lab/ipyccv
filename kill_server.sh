#!/usr/bin/env bash

# Kill previous server
PREV_SERVER=$(ssh sven2guest@vm "ps -x | grep forward_server | grep -v grep | cut -b1-5" | sed -z 's/\n/ /'g)
if [[ ! -z "$PREV_SERVER" ]]; then
    echo "Klling $PREV_SERVER"
    ssh vm "kill -9 $PREV_SERVER"
fi
