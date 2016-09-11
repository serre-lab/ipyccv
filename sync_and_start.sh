#!/bin/bash

# Kill previous server
PREV_SERVER=$(ssh sven2guest@vm "ps -x | grep forward_server | grep -v grep | cut -b1-5" | sed -z 's/\n/ /'g)
if [[ ! -z "$PREV_SERVER" ]]; then
    echo "Klling $PREV_SERVER"
    ssh vm "kill -9 $PREV_SERVER"
fi
ssh -T guest018@ccv "bash ~/bin/killnb.sh"
# Update data packages
./syncscript.sh

# Restart server
ssh -tt sven2guest@vm "cd ipyccv; ./forward_server.py"
