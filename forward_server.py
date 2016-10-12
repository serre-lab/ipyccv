#!/usr/bin/env python

from flask import Flask, request, render_template, session, send_from_directory, make_response, redirect, url_for
from flask.ext.session import Session
from threading import Thread
from paramiko.client import SSHClient
from paramiko import AutoAddPolicy
from sshtunnel import SSHTunnelForwarder
import os, time, select
from paramiko.ssh_exception import SSHException
import sys
import datetime

#SSL_CERT_FILENAME = '/home/sven2guest/babas.crt'
#SSL_KEY_FILENAME = '/home/sven2guest/babas.key'
SSL_CERT_FILENAME = '/home/sven2guest/__clps_brown_edu_cert.cer'
SSL_KEY_FILENAME = '/home/sven2guest/.ssh/star_clps_brown_edu_20160413.key'

app = Flask(__name__)
SESSION_TYPE = 'redis'
app.config.from_object(__name__)
Session(app)

# Forward info
class ClientData:
    def __init__(self, username, password, package):
        self.username = username
        self.password = password
        self.package = package
        self.error = None
        self.connection_info = 'init ssh'
        self.connect_thread = None
        self.client = None
        self.tunnel = None
        self.node_name = None
        self.node_port = None
        self.local_tunnel_port = None
        self.remote_tunnel_port = None
        self.notebook_password = None
        self.next_command = ''
        self.last_log = None
        self.last_query_time = None
        self.time_left_until_kill = None

    # Notebook file lists
    NOTEBOOK_FILE_LIST = {
        'matlab1520': {
            'directory listing': '/tree',
            'Tutorial 1': '/notebooks/Tutorial_1.ipynb',
            'Tutorial 2': '/notebooks/Tutorial_2.ipynb',
            'Tutorial 3': '/notebooks/Tutorial_3.ipynb',
            'Tutorial 4': '/notebooks/Tutorial_4.ipynb',
            'Tutorial 5': '/notebooks/Tutorial_5.ipynb'
        }
    }

    # Kill connection if no request came in this duration
    TIMEOUT_SECONDS = 60*10

    def connect(self):
        self.refresh_query_time()
        if self.connect_thread is None:
            self.connect_thread = Thread(target=self._connect)
            self.connect_thread.start()

    def refresh_query_time(self):
        self.last_query_time = datetime.datetime.now()

    def get_error(self): return self.error

    def get_last_log(self): return self.last_log

    def get_forwards(self, request_url):
        if self.local_tunnel_port is None: return None
        this_hostname = request_url.split('/')[2].split(':')[0]
        url = 'http://' + this_hostname + ':' + str(self.local_tunnel_port) + '/login?next='
        return [{'name': name, 'url': url + path.replace('/', '%2F')} for name, path in ClientData.NOTEBOOK_FILE_LIST[self.package].iteritems()]

    def get_connection_info(self):
        connection_info = self.connection_info
        if self.time_left_until_kill is not None:
            connection_info += '\nIdle time until kill: %d seconds' % self.time_left_until_kill
        self.refresh_query_time()
        return connection_info

    def get_notebook_password(self): return self.notebook_password

    def kill_job(self):
        self.next_command = ' KILL'

    # Background thread ------------------------------
    script_filename = './nbsched.sh'
    script_download_url = 'https://babas.clps.brown.edu:11000/data/nbsched.sh'
    cluster_server = 'ssh.ccv.brown.edu'
    available_local_ports = set(range(11001, 12000))

    @staticmethod
    def acquire_local_port():
        return ClientData.available_local_ports.pop()

    @staticmethod
    def release_local_port(port):
        return ClientData.available_local_ports.add(port)

    def _connect(self):
        # In background thread: Start server
        try:
            # Initiate connection
            self.connection_info = 'ssh connecting'
            self.client = SSHClient()
            self.client.load_system_host_keys()
            self.client.set_missing_host_key_policy(AutoAddPolicy())
            self.client.connect(ClientData.cluster_server, username=self.username, password=self.password)
            self.channel = self.client.invoke_shell()
            # Download script file if necessery
            self.connection_info = 'Setup environment'
            self.exec_command('wget --no-check-certificate -q ''%s'' -O %s ; chmod +x %s' % (ClientData.script_download_url, ClientData.script_filename, ClientData.script_filename)) # -N only if newer?
            self.connection_info = 'Starting server'
            self.last_jobid = None
            # Run scheduler script until successful
            self.refresh_query_time()
            while True:
                result = self.exec_command(ClientData.script_filename + ' ' + self.package + self.next_command)
                self.next_command = ''
                #print 'Output =', result
                result_lines = result.splitlines()
                result_data = None
                for r in result_lines:
                    if 'JOB ' in r:
                        result_data = {}
                        for i,v in enumerate(r.split(' ')):
                            result_data[i] = v
                        break
                is_running = False
                if result_data is None:
                    #raise RuntimeError('unexpected output: %s' % result)
                    sys.stderr.write('unexpected output: %s\n' % result)
                else:
                    status = result_data[1]
                    if status == 'OFF':
                        self.connection_info = 'Scheduling job'
                    elif status == 'QUEUED':
                        self.connection_info = 'Waiting for job allocation (reason: %s).\nEstimated start: %s' % (result_data.get(2), result_data.get(3))
                    elif status == 'INIT':
                        self.connection_info = 'Initializing notebook on node %s.\nJob ID: %s\nRemaining node time: %s' % (result_data.get(2), result_data.get(3), result_data.get(4))
                        self.last_jobid = result_data.get(3)
                    elif status == 'RUNNING':
                        self.node_name = result_data.get(2)
                        self.node_port = int(result_data.get(3, 0))
                        self.last_jobid = int(result_data.get(4))
                        rem_time = result_data.get(5)
                        self.notebook_password = result_data.get(6)
                        self.connection_info = 'Running notebook on node %s port %d.\nRemaining node time: %s.' % (self.node_name, self.node_port, rem_time.strip())
                        # Ensure tunnel is running
                        if self.remote_tunnel_port != self.node_port:
                            self.connection_info += '\nConnecting tunnel...'
                            if self.tunnel is not None:
                                self.stop_tunnel()
                            remote_bind_address = (self.node_name, self.node_port)
                            local_bind_address = ('0.0.0.0', ClientData.acquire_local_port())
                            print 'Tunneling from %s to %s...' % (remote_bind_address, local_bind_address)
                            self.tunnel = SSHTunnelForwarder(ClientData.cluster_server,
                                                 ssh_username=self.username, ssh_password=self.password,
                                                 remote_bind_address=remote_bind_address,
                                                 local_bind_address=local_bind_address)
                            self.tunnel.start()
                            self.remote_tunnel_port = self.node_port
                        self.connection_info += '\nTunnel open on port %d.' % self.tunnel.local_bind_port
                        self.local_tunnel_port = self.tunnel.local_bind_port
                        is_running = True
                    elif status == 'KILL':
                        self.connection_info = 'Killed job'
                    if not is_running:
                        self.local_tunnel_port = None
                # Log file if there's a job running
                if self.last_jobid is not None:
                    self.last_log = self.exec_command('cat logs/slurm-%s.out' % self.last_jobid)
                # Update interval: High during initialization; slow down later
                time.sleep(10.0 if is_running else 1.0)
                # Kill server if no request came in a while
                self.time_left_until_kill = int(ClientData.TIMEOUT_SECONDS - (datetime.datetime.now() - self.last_query_time).total_seconds())
                print 'User %s time left: %d seconds' % (self.username, self.time_left_until_kill)
                if self.time_left_until_kill < 0:
                    raise RuntimeError('Session timed out')
            # Done
            self.connect_thread = None
            self.time_left_until_kill = None

        except Exception as e:
            sys.stderr.write('============================\nKILLING SESSION FOR USER %s!\n%s\n============================\n' % (self.username, e.message))
            self.forward = None
            self.error = e.message
            self.clear()
            self.connect_thread = None
            print e

    def stop_tunnel(self):
        if self.tunnel is not None:
            self.tunnel.stop()
            self.tunnel.close()
            self.tunnel = None
        if self.local_tunnel_port is not None:
            print 'Released tunnel from port %d.' % self.local_tunnel_port
            ClientData.release_local_port(self.local_tunnel_port)
        self.local_tunnel_port = None
        self.remote_tunnel_port = None

    def clear(self):
        self.stop_tunnel()
        if self.client is not None:
            self.client.close()
            self.client = None
        self.notebook_password = None
        self.time_left_until_kill = None

    def exec_command(self, cmd):
        sys.stderr.write('Executing %s\n' % cmd)
        #cmd = './nbsched.sh'
        stdin, stdout, stderr = self.client.exec_command('bash -c "%s"' % cmd, get_pty=True)
        # Wait for the command to terminate
        output_data = ''
        done = False
        while not done:
            # Done?
            if stdout.channel.exit_status_ready():
                done = True
            # Only print data if there is data to read in the channel
            if stdout.channel.recv_ready():
                rl, wl, xl = select.select([stdout.channel], [], [], 0.0)
                if len(rl) > 0:
                    output_data += stdout.channel.recv(1024).decode('utf-8', 'ignore')
            # Double login
            if 'oscar\'s password' in output_data:
                #print('Extra login... (data was: %s)' % output_data)
                output_data = ''
                stdin.write(self.password + '\n')
            # Answer question about first-time setup
            if 'Are you sure you want to continue connecting (yes/no)?' in output_data:
                #print('Confirmation... (data was: %s)' % output_data)
                output_data = ''
                stdin.write('yes\n')
        output_data += stdout.read().decode('utf-8', 'ignore')
        output_data = output_data.strip().encode('ascii', 'ignore').decode('ascii', 'ignore')
        #sys.stderr.write('Output: %s\n' % output_data)
        error = stderr.read()
        if len(error):
            sys.stderr.write('ERROR: %s\n' % error)
            raise RuntimeError(error)
        return output_data

# Forwards by username
client_data = dict()

@app.route('/main', methods=['GET', 'POST'])
def main():
    # Handle login
    if request.method == 'POST':
        password = request.form["password"]
        username = request.form["username"]
        package = request.form["package"]
        if not username.isalnum() or not len(username):
            return render_template('login.html', error='Invalid username', username=username, password=password)
        session['username'] = username
        session['password'] = password
        session['package'] = package
    username = session.get('username', '')
    password = session.get('password', '')
    package = session.get('package', '')
    if not len(username) or not len(password):
        return render_template('login.html', error='Enter credentials', username=username, password=password)
    # Client data lookup
    client_data_name = username + ' ' + password
    if not client_data_name in client_data:
        data = ClientData(username, password, package)
        client_data[client_data_name] = data
        data.connect()
    else:
        data = client_data[client_data_name]
    # Render by current status
    forwards = data.get_forwards(request.url)
    r = render_template('main.html', error=data.get_error(), forwards=forwards, connection_info=data.get_connection_info(), nbpasswd=data.get_notebook_password(), package=package, last_log=data.get_last_log())
    # Restart server on error
    if data.get_error() is not None:
        data.connect()
    #r = make_response(r)
    #if forward is not None:
    #    r.headers.set('Content-Security-Policy', "default-src 'same' %s" % forward)
    return r

@app.route('/reset_connection')
def reset_connection():
    username = session.get('username', '')
    password = session.get('password', '')
    client_data_name = username + ' ' + password
    if client_data_name in client_data:
        data = client_data[client_data_name]
        data.clear()
        del client_data[client_data_name]
    return redirect(url_for('main'))

@app.route('/kill_job')
def kill_job():
    username = session.get('username', '')
    password = session.get('password', '')
    client_data_name = username + ' ' + password
    if client_data_name in client_data:
        client_data[client_data_name].kill_job()
    return redirect(url_for('main'))

@app.route('/')
def root():
    return render_template('login.html')

@app.route('/data/<path:filename>', methods=['GET', 'POST'])
def download(filename):
    data_dir = os.path.join(app.root_path, 'data')
    return send_from_directory(directory=data_dir, filename=filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=11000, debug=False, ssl_context=(SSL_CERT_FILENAME, SSL_KEY_FILENAME))
