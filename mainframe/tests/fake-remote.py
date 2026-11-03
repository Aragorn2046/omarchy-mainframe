#!/usr/bin/env python3
"""Local process fixture for collector session tests; never invokes SSH."""
import json
import os
import sys
import time
os.setpgid(0, 0)
sys.stdin.read()
while True:
    print(json.dumps({'host': 'fixture', 'os': 'linux', 'wsl': True, 'filesystems': [{'device':'/dev/a','mount':'/','total':1000,'used':850}, {'device':'C:','mount':'C:','total':2000,'used':1900}, {'device':'/dev/b','mount':'/media/data','total':3000,'used':900}]}), flush=True)
    time.sleep(0.5)
