#!/usr/bin/env python
# -*- coding: utf-8 -*-
'''
Copyright (c) 2013 Qin Xuye <qin@qinxuye.me>

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Created on 2014-6-8

@author: chine
'''

import os
import threading
import socket
import shutil

from cola.core.utils import import_job_desc, Clock, pack_local_job_error
from cola.core.rpc import FileTransportServer, client_call, FileTransportClient
from cola.core.zip import ZipHandler
from cola.core.logs import get_logger
from cola.job import Job

HEARTBEAT_INTERVAL = 20

class WorkerJobInfo(object):
    def __init__(self, job_name, working_dir):
        self.job_name = job_name
        self.working_dir = working_dir
        
        self.job = None
        self.thread = None
        self.clock = None

class Worker(object):
    def __init__(self, ctx):
        self.ctx = ctx
        self.master = self.ctx.master_addr
        addr_dirname = self.ctx.addr.replace('.', '_').replace(':', '_')
        self.working_dir = os.path.join(self.ctx.working_dir, 'worker', addr_dirname)
        self.job_dir = os.path.join(self.working_dir, 'jobs')
        self.zip_dir = os.path.join(self.working_dir, 'zip')
        self.running_jobs = {}
        
        self.rpc_server = self.ctx.worker_rpc_server
        assert self.rpc_server is not None
        self._register_rpc()
        
        self.stopped = threading.Event()
        
        self.logger = get_logger('cola_worker', server=self.ctx.master_ip)
        
        self._ensure_exists(self.job_dir)
        self._ensure_exists(self.zip_dir)
        FileTransportServer(self.rpc_server, self.zip_dir)
        
    def _ensure_exists(self, dir_):
        if not os.path.exists(dir_):
            os.makedirs(dir_)
        
    def _register_rpc(self):
        if self.rpc_server:
            self.rpc_server.register_function(self.prepare, 'prepare')
            self.rpc_server.register_function(self.run_job, 'run_job')
            self.rpc_server.register_function(self.has_job, 'has_job')
            self.rpc_server.register_function(self.stop_running_job, 
                                              'stop_job')
            self.rpc_server.register_function(self.clear_running_job,
                                              'clear_job')
            self.rpc_server.register_function(self.pack_job_error,
                                              'pack_job_error')
            self.rpc_server.register_function(self.add_node, 'add_node')
            self.rpc_server.register_function(self.remove_node, 'remove_node')
            self.rpc_server.register_function(self.shutdown, 'shutdown')
            
    def run(self):
        def _report():
            while not self.stopped.is_set():
                workers = client_call(self.master, 'register_heartbeat', 
                                      self.ctx.worker_addr)
                self.ctx.addrs = [self.ctx.fix_addr(worker) for worker in workers]
                self.ctx.ips = [self.ctx.fix_ip(worker) for worker in workers]
                                
                self.stopped.wait(HEARTBEAT_INTERVAL)
        
        self._t = threading.Thread(target=_report)
        self._t.start()
        
    def _unzip(self, job_name):
        zip_file = os.path.join(self.zip_dir, job_name+'.zip')
        job_path = os.path.join(self.job_dir, job_name)
        if os.path.exists(job_path):
            shutil.rmtree(job_path)
        if os.path.exists(zip_file):
            ZipHandler.uncompress(zip_file, self.job_dir)
        
    def prepare(self, job_name, unzip=True, overwrite=False, 
                settings=None):
        self.logger.debug('entering worker prepare phase, job id: %s' % job_name)
        if unzip:
            self._unzip(job_name)
        
        src_job_name = job_name
        job_path = os.path.join(self.job_dir, job_name)
        
        if not os.path.exists(job_path):
            return False
        
        job_desc = import_job_desc(job_path)
        if settings is not None:
            job_desc.update_settings(settings)
        
        job_id = self.ctx.ips.index(self.ctx.ip)
        clear = job_desc.settings.job.clear \
                    if self.ctx.is_local_mode else False
        job_name, working_dir = self.ctx._get_name_and_dir(
            self.working_dir, job_name, overwrite=overwrite, clear=clear)
        
        job = Job(self.ctx, job_path, job_name, job_desc=job_desc,
                  working_dir=working_dir, rpc_server=self.rpc_server,
                  manager=self.ctx.manager, job_offset=job_id)
        t = threading.Thread(target=job.run, args=(True, ))
        
        job_info = WorkerJobInfo(job_name, working_dir)
        job_info.job = job
        job_info.thread = t
        self.running_jobs[src_job_name] = job_info
        
        self.logger.debug('worker prepare phase finished, job id: %s' % job_name)
        return True
        
    def run_job(self, job_name):
        self.logger.debug('entering worker run phase, job id: %s' % job_name)
        if job_name not in self.running_jobs:
            self.logger.debug(
                'job not prepared, refused to run, job id: %s' % job_name)
            return False
        
        job_info = self.running_jobs[job_name]
        
        clock = Clock()
        job_info.clock = clock
        job_info.thread.start()
        
        self.logger.debug('worker starts to run job, id: %s' % job_name)
        return True
        
    def stop_running_job(self, job_name):
        job_info = self.running_jobs.get(job_name)
        if job_info:
            job_info.job.stop_running()
            
    def clear_running_job(self, job_name):
        job_info = self.running_jobs.get(job_name)
        if job_info:
            job_info.job.clear_running()
            job_info.thread.join()
            del self.running_jobs[job_name]
            return job_info.clock.clock()
    
    def has_job(self, job_name):
        return job_name in self.running_jobs
    
    def pack_job_error(self, job_name):
        working_dir = os.path.join(self.working_dir, job_name)
        pack_dir = pack_local_job_error(job_name, working_dir=working_dir, 
                                        logger=self.logger)
        zip_filename = os.path.join(self.zip_dir,
                                    '%s_%s_errors.zip'%(self.ctx.ip.replace('.', '_'), job_name))
        if os.path.exists(zip_filename):
            os.remove(zip_filename)
        
        ZipHandler.compress(zip_filename, pack_dir)
        FileTransportClient(self.master, zip_filename).send_file()
        
    def add_node(self, worker):
        self.ctx.add_node(worker)
        for job_info in self.running_jobs.values():
            job_info.job.add_node(worker)
            
    def remove_node(self, worker):
        self.ctx.remove_node(worker)
        for job_info in self.running_jobs.values():
            job_info.job.remove_node(worker)
            
    def shutdown(self):
        if not hasattr(self, '_t'):
            return
        
        self.logger.debug('worker starts to shutdown')
        
        for job_info in self.running_jobs.values():
            job_info.job.shutdown()
            job_info.thread.join()

        try:
            self.ctx.manager.shutdown()
        except socket.error:
            pass
            
        self.stopped.set()
        self._t.join()
        
        self.rpc_server.shutdown()
        self.logger.debug('worker shutdown finished')