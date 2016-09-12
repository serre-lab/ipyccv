#!/bin/bash
# This script queues an ipython notebook server or returns its status if it is already queued
# When started without parameters, the script will output a single line starting with JOB:
# JOB OFF                                - No job found. A new ipython job will be started.
# JOB QUEUED <reason> <est. start>       - iPython notebook job has been queued but no node allocated yet. 
# JOB INIT <node> <jobid> <rem time>     - The job has been starting on <node> but the process is still initializing.
# JOB RUNNING <node> <port> <jobid> <rem time> <password>   - The notebook is running on node <node> and port <port>. <rem time> is the remaining time until it will be killed.
# 
# Usage: nbsched.sh package [command]
# The package should have a corresponding setup script in data
# Commands:
#  START  - this script will launch a jupyter notebook directly
#  KILL   - kill any previously started notebook
# Output logs are created in subfolder logs/

PACKAGE="$1"
NOTEBOOKPATH="$HOME/scratch/${PACKAGE}"
NOTEBOOKDOWNLOAD=https://babas.clps.brown.edu:11000/data/${PACKAGE}.tar.gz

# Start notebook directly?
if [[ "$2" == "START" ]]; then
    echo "Starting notebook package $1... ($HASHPASS)"
	# Setup paths and download the notebook if not done yet
	if [ ! -d "$NOTEBOOKPATH" ]; then
		echo "Creating notebook path..."
		mkdir "$NOTEBOOKPATH"
	fi
	cd "$NOTEBOOKPATH"
	echo "Loading notebook package from $NOTEBOOKDOWNLOAD..."
	echo wget --no-check-certificate -N "$NOTEBOOKDOWNLOAD" -O ${PACKAGE}.tar.gz
	wget --no-check-certificate -N "$NOTEBOOKDOWNLOAD" -O ${PACKAGE}.tar.gz
	echo "Unpacking notebook scripts..."
	tar -zxvf ${PACKAGE}.tar.gz ${PACKAGE}_setup.sh ${PACKAGE}_start.sh
	echo "Unpacking notebooks..."
	tar -zxvf ${PACKAGE}.tar.gz --keep-old-files
	# Perform setup
	echo "Run setup..."
	if [ -f "${PACKAGE}_setup.sh" ]; then
		sh ${PACKAGE}_setup.sh
	else
	    echo MISSING SETUP
	    exit
	fi
	# Generate a password
	echo "Generating temporary password..."
	< /dev/urandom tr -dc _A-Za-z0-9 | head -c 32 >passwd
	# Hash it to be used on jupyter command line
	HASHPASS=$(python -c "from IPython.lib import passwd; import fileinput; print(passwd(fileinput.input().readline()))" <passwd)
	# (TODO: Better to have it in a config file than passing the hashed pass via command line (where it can be spoofed via ps))
	# Start notebook server.
	# Port may change if already in use. That's fine it's picked up by the forwarder
	echo "Starting ${PACKAGE}_start.sh..."
	sh ${PACKAGE}_start.sh "$HASHPASS"
	exit
fi

# Get job status string of running ipython job
JOBSTATUS=$(squeue -h -u $USER --format="%i %j %t %N %L %R %S" -t R,PD -S L | grep -m 1 $(basename "$0"))
echo "Status result: $JOBSTATUS"
if [[ -z "$JOBSTATUS" ]]; then
	# No job is running. Queue ourselves with START parameter, which will start the actual notebook.
	echo JOB OFF
	mkdir -p logs
	sbatch -p bibs-gpu --gres=gpu:1 --mem=32g -t 3:00:00 -o logs/slurm-%j.out "$0" "$PACKAGE" START
	if [ $? -ne 0 ]; then
	    sbatch --mem=32g -t 3:00:00 -o logs/slurm-%j.out "$0" "$PACKAGE" START
	fi
else
	# Job is running. Extract status fields
	JOBID=$(echo $JOBSTATUS | cut -d " " -f 1)
	JOBSTATUSCLASS=$(echo $JOBSTATUS | cut -d " " -f 3)
	NODE=$(echo $JOBSTATUS | cut -d " " -f 4)
	REMTIME=$(echo $JOBSTATUS | cut -d " " -f 5)
	REASON=$(echo $JOBSTATUS | cut -d " " -f 6)
	EXPECTEDSTART=$(echo $JOBSTATUS | cut -d " " -f 7)
	# Job to be killed?
	if [[ "$2" == "KILL" ]]; then
		scancel $JOBID
		echo JOB KILLED
		exit
	fi
	# Pending or started? Pending jobs show the reason in brackets.
	if [[ "$JOBSTATUSCLASS" == "PD" ]]; then
		# Job still pending.
		echo JOB QUEUED $REASON $EXPECTEDSTART
	else
		# Slurm job output file created?
		LOGFILE="logs/slurm-${JOBID}.out"
		if [ ! -f "$LOGFILE" ]; then
			# No output file yet.
			echo JOB QUEUED STARTUP $EXPECTEDSTART
		else
			# Read status from slurm output file
			PORT=$(cat "logs/slurm-${JOBID}.out" | grep "Notebook is running at" | sed -n 's/^.*[^0-9]\([0-9][0-9]*\).*/\1/p')
			if [[ -z "$PORT" ]]; then
				# Port not found in status log. Probably not running yet.
				echo JOB INIT $NODE $JOBID $REMTIME
			else
				# Yeah, it's running!
				NBPASS=$(cat "$NOTEBOOKPATH"/passwd)
				echo JOB RUNNING $NODE $PORT $JOBID $REMTIME $NBPASS
			fi
		fi
	fi
fi
