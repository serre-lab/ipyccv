#!/usr/bin/env bash

module load matlab/R2016a
module load python/3.4.1
module load gcc/4.9.2
module load git

# Setup virtual environment
if [ ! -d p3 ]; then
    # First time setup
    virtualenv --system-site-packages p3
    source p3/bin/activate
    PSAVE=$PWD
    cd $MATLAB_ROOT/extern/engines/python
    python3 setup.py build --build-base="$HOME/scratch/matlabp3" install
    cd $PSAVE
    pip install -Iv setuptools ipykernel ipywidgets notebook
    pip install git+https://github.com/Calysto/matlab_kernel@4372db233374979668add9dc3deb80063f6d0f20
    #pip install -Iv matlab_kernel backports.shutil_get_terminal_size pathlib2
    python -m matlab_kernel install --user
    # Matlab with JVM startup
    ln -s $(which matlab-threaded) ./p3/bin/matlab
fi

if [ !-d $HOME/.local/share/jupyter/kernels/matlab]; then
    source p3/bin/activate
    python -m matlab_kernel install --user
fi
