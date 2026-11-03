#!/usr/bin/env python3
"""Offline local sample for offscreen view tests."""
import json
import time
counter = 0
while True:
    counter += 1
    print(json.dumps({'host':'fixture-local', 'os':'linux', 't_ms':int(time.time()*1000), 'mono_ms':int(time.monotonic()*1000), 'cpu':{'total':{'user':counter*10,'system':counter*5,'idle':counter*85},'cores':[]}, 'mem':{'total':8000000000,'used':3000000000,'available':5000000000,'cached':1000000000,'swapUsed':0,'swapTotal':0}, 'filesystems':[{'device':'/dev/fixture','mount':'/','total':1000,'used':500}]}), flush=True)
    time.sleep(1)
