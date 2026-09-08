import signal, sys, time
def _h(s, f):
    print("BIZ_TERM_RECEIVED", flush=True)
    time.sleep(2.0)
    sys.exit(0)
signal.signal(signal.SIGTERM, _h)
print("BIZ_READY", flush=True)
time.sleep(120)
