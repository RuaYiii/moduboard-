import collections
import datetime

# 存储最近 50 条日志
system_logs = collections.deque(maxlen=50)

def add_log(msg: str):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    system_logs.appendleft({"timestamp": now, "message": msg})
    print(f" [实时日志] [{now}] {msg}")
