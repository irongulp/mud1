"""Foreground MariaDB with a private socket and optional managed loopback editor."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import threading
import time

START_TIMEOUT=60
STOP_TIMEOUT=30
MAX_TCP_PORT=65535
LISTENER_CONFIG='listener.json'
LISTENER_CONFIG_LIMIT=4096


def listener_options(port):
    if port is None: return ['--skip-networking']
    if type(port) is not int or not 1<=port<=MAX_TCP_PORT: raise ValueError('Invalid database TCP port')
    return ['--bind-address=127.0.0.1','--port='+str(port),'--skip-name-resolve']


def configured_port(directory):
    from tools.persona_snapshot import private_read,strict_json
    path=Path(directory)/LISTENER_CONFIG
    if not path.exists(): return None
    if path.is_symlink(): raise ValueError('Database listener config must not be a symlink')
    value=strict_json(private_read(path,LISTENER_CONFIG_LIMIT))
    if (not isinstance(value,dict) or set(value)!={'format_version','port'}
            or type(value['format_version']) is not int or value['format_version']!=1):
        raise ValueError('Unrecognized database listener config')
    listener_options(value['port'])
    if value['port'] is None: raise ValueError('Configured listener must have a port')
    return value['port']


def server_program():
    value=shutil.which('mariadbd') or shutil.which('mysqld')
    if value: return value
    for value in ('/usr/libexec/mariadbd','/usr/sbin/mariadbd','/usr/libexec/mysqld','/usr/sbin/mysqld'):
        if Path(value).is_file(): return value
    raise RuntimeError('MariaDB server executable is not installed')


class PrivateDatabase:
    def __init__(self,directory):
        self.directory=Path(directory).resolve(); self.socket=self.directory/'db.sock'
        self.process=None; self.log=None
    def admin(self):
        import pymysql
        return pymysql.connect(unix_socket=str(self.socket),user='root',password='',autocommit=True,
                               connect_timeout=1,read_timeout=5,write_timeout=5,charset='utf8mb4',binary_prefix=True)
    def initialize(self):
        self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        if self.directory.stat().st_mode & 0o077: raise RuntimeError('Database state must be private')
        marker=self.directory/'initialized.json'
        if marker.exists():
            if not (self.directory/'data/mysql').is_dir(): raise RuntimeError('Database marker has no system tables')
            return
        if (self.directory/'data').exists(): raise RuntimeError('Interrupted database initialization; preserve it for inspection')
        (self.directory/'tmp').mkdir(mode=0o700,exist_ok=True)
        executable=server_program()
        initializer=shutil.which('mariadb-install-db') or shutil.which('mysql_install_db')
        if not executable or not initializer: raise RuntimeError('MariaDB server tools are missing')
        with (self.directory/'initialize.log').open('wb') as log:
            subprocess.run([initializer,'--no-defaults','--datadir='+str(self.directory/'data'),
                            '--tmpdir='+str(self.directory/'tmp'),'--auth-root-authentication-method=normal','--skip-test-db'],
                           check=True,stdout=log,stderr=subprocess.STDOUT,timeout=120)
        from tools.persona_snapshot import publish_private
        publish_private(marker,lambda stream:stream.write(b'{"initialized":true}\n'))
    def start(self):
        self.initialize()
        executable=server_program()
        self.log=(self.directory/'process.log').open('ab')
        self.process=subprocess.Popen([executable,'--no-defaults','--datadir='+str(self.directory/'data'),
            '--socket='+str(self.socket),'--pid-file='+str(self.directory/'db.pid'),'--tmpdir='+str(self.directory/'tmp'),
            *listener_options(configured_port(self.directory)),
            '--skip-log-bin','--general-log=0','--slow-query-log=0','--default-time-zone=+00:00',
            '--innodb-buffer-pool-size=64M','--performance-schema=OFF','--event-scheduler=OFF',
            '--log-error='+str(self.directory/'server.log')],stdout=self.log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+START_TIMEOUT
        while time.monotonic()<deadline:
            if self.process.poll() is not None: raise RuntimeError('Private MariaDB exited during startup')
            try:
                with self.admin(): return
            except Exception: time.sleep(.1)
        raise TimeoutError('Private MariaDB readiness timed out')
    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try: self.process.wait(timeout=STOP_TIMEOUT)
                except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()
            self.process=None
        if self.log is not None: self.log.close(); self.log=None
    def __enter__(self):
        try: self.start(); return self
        except BaseException: self.stop(); raise
    def __exit__(self,*exc): self.stop()


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args(); stopped=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,lambda *_:stopped.set())
    from server.runtime import notify
    with PrivateDatabase(args.directory) as database:
        notify('READY=1\nSTATUS=Private external persona database is ready')
        while not stopped.wait(1):
            if database.process.poll() is not None: raise RuntimeError('Private MariaDB exited')
        notify('STOPPING=1')


if __name__=='__main__': main()
