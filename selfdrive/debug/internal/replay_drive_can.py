#!/usr/bin/env python3

import time
from tqdm import tqdm
from tools.lib.logreader import LogReader
import cereal.messaging as messaging

ROUTE = "77611a1fac303767/2020-03-24--09-50-38"
NUM_SEGS = 10 # route has 82 segments available

# Get can messages from logs
print("Loading...")
can_msgs = []
for i in tqdm(list(range(1, NUM_SEGS))):
  log_url = f"https://commadataci.blob.core.windows.net/openpilotci/{ROUTE}/{i}/rlog.bz2"
  lr = LogReader(log_url)
  can_msgs += [m for m in lr if m.which() == 'can']


# Replay
print("Replay...")
can = messaging.pub_sock('can')
while True:
  for m in tqdm(can_msgs):
    can.send(m.as_builder().to_bytes())
    time.sleep(0.01)  # 100 Hz
