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

Created on 2013-5-23

@author: Chine
'''

class Unit(object):
    def __init__(self, item, force=False, priority=0):
        self.item = item
        self.force = force
        self.priority = priority
    
    def __str__(self):
        raise NotImplementedError


class Url(Unit):
    def __init__(self, url, force=False, priority=0):
        super(Url, self).__init__(url, force=force, 
                                  priority=priority)
        self.url = url
        
    def __str__(self):
        return self.url
    
    def __eq__(self, url):
        if url is None:
            return False
        if isinstance(url, unicode):
            url = url.encode('utf-8')
        if isinstance(url, str):
            return self.url == url
        if not isinstance(url, Url):
            return False
        return self.url == url.url


class Bundle(Unit):
    '''
    Sometimes the target is all the urls about a user.
    Then the urls compose the bundle.
    So a bundle can generate several urls.
    '''
    
    def __init__(self, label, force=False, priority=0):
        if not isinstance(label, str):
            raise ValueError("Bundle's label must a string.")
        super(Bundle, self).__init__(label, force=force,
                                     priority=priority)
        self.label = label
        
        self.error_urls = []
        self.current_urls = []
        
    def urls(self):
        raise NotImplementedError
    
    def __str__(self):
        return self.label