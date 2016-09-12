#!/usr/bin/env bash

module load gcc/4.9.2
module load python/3.4.1
module load matlab/R2016a
module load matconvnet/1.0-beta20-gpu
source p4/bin/activate
python -m matlab_kernel install --user
ipython notebook --ip=* --port 8889 --no-browser --NotebookApp.password="$1"
