#!/usr/bin/env bash
# Runs the tensorflow notebooks. Notebook password in $1

module load tensorflow
export LD_PRELOAD=/gpfs/runtime/opt/gcc/4.9.2/lib64/libstdc++.so.6
ipython notebook --ip=* --port 8889 --no-browser --NotebookApp.password="$1"
