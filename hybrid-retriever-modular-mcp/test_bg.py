import time
import threading

_t = None
def work():
    time.sleep(2)
    print("done")

_t = threading.Thread(target=work, daemon=True)
_t.start()
print("main done")
