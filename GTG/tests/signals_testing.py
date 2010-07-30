import threading
import gobject
import time
import unittest

from GTG.tools.watchdog import Watchdog



class SignalCatcher(object):
    '''
    A class to test signals
    '''


    def __init__(self, unittest,  generator, signal_name,\
                 should_be_caught = True):
        self.signal_catched_event = threading.Event()
        self.generator = generator
        self.signal_name = signal_name
        self.signal_arguments = []
        self.unittest = unittest
        self.should_be_caught = should_be_caught

        def _on_failure():
            #we need to release the waiting thread
            self.signal_catched_event.set()
            self.missed = True
            #then we notify the error
            self.unittest.assertFalse(should_be_caught)

        self.watchdog = Watchdog(3, _on_failure)

    def __enter__(self):

        def __signal_callback(*args):
            del self.signal_arguments[:]
            self.signal_arguments.extend(args[1:])
            self.signal_catched_event.set()

        self.handler = \
                self.generator.connect(self.signal_name, __signal_callback)
        self.watchdog.__enter__()
        return [self.signal_catched_event, self.signal_arguments]

    def __exit__(self, err_type, value, traceback):
        self.generator.disconnect(self.handler)
        if not self.should_be_caught and not hasattr(self, 'missed'):
            self.assertFalse(True)
        return not isinstance(value, Exception) and \
                self.watchdog.__exit__(err_type, value, traceback)
    


class GobjectSignalsManager(object):
    

    def init_signals(self):
        '''
        Initializes the gobject main loop so that signals can be used.
        This function returns only when the gobject main loop is running
        '''
        def gobject_main_loop():
            gobject.threads_init()
            self.main_loop = gobject.MainLoop()
            self.main_loop.run()
        threading.Thread(target = gobject_main_loop).start()
        while not hasattr(self, 'main_loop') or \
              not self.main_loop.is_running():
            #since running the gobject main loop is a blocking call, we have to
            #check that it has been started in a polling fashion
            time.sleep(0.1)

    def terminate_signals(self):
        self.main_loop.quit()

