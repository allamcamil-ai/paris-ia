import multiprocessing

bind = "0.0.0.0:10000"
workers = 1
threads = 2
preload_app = True
timeout = 120

def on_starting(server):
    """Called just before the master process is initialized."""
    pass
