#!/usr/bin/env python

from paramiko.client import SSHClient
from paramiko import AutoAddPolicy
import select

client = SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(AutoAddPolicy())
client.connect('ssh.ccv.brown.edu', username='guest012', password='zzT56UT3')
print 'connected.'

def exec_command(cmd):
    # print 'Executing %s' % cmd
    # cmd = './nbsched.sh'
    stdin, stdout, stderr = client.exec_command('bash -c "%s"' % cmd, get_pty=True)
    # Wait for the command to terminate
    output_data = ''
    while not stdout.channel.exit_status_ready():
        # Only print data if there is data to read in the channel
        if stdout.channel.recv_ready():
            rl, wl, xl = select.select([stdout.channel], [], [], 0.0)
            if len(rl) > 0:
                output_data += stdout.channel.recv(1024).decode('utf-8')
        if 'Are you sure you want to continue connecting (yes/no)?' in output_data:
            output_data = ''
            stdin.write('yes\n')
            print 'Connection allowed.'
    error = stderr.read()
    if len(error): raise RuntimeError(error)
    return output_data

result = exec_command('blabla echo test')
print result
