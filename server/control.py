#!/usr/bin/env python

import os, sys, signal
from classes.server import Server

# Get the absolute directory of control.py
current_dir = os.path.abspath(os.path.dirname(sys.argv[0]))

# Read the process id from a file and then deletes the file
#
def read_pid():
    f = open(current_dir + "/pid", "r")
    pid = int(f.readline())
    f.close()
    os.remove(current_dir + "/pid")
    return pid

if (len(sys.argv) != 2):
    print "Please specify an argument"
else:
    if (sys.argv[1] == "start"):
        if (not os.path.exists(current_dir + "/pid")):
            Server(current_dir, ["drinc"], "live.conf").start()
        else:
            print "PID file exists, probable that server is already running. Check the server is running by using \"ps aux\" and if the server is actually not running, manually delete the pid file."
    elif (sys.argv[1] == "stop"):
        try:
            os.kill(read_pid(), signal.SIGKILL)
        except IOError:
            print "Cannot find pid file, probable that server is not running. Use \"ps aux\" to check if the server is still running and kill it if required."
        else:
            print "Server stopped"
    else:
        print "Unrecognised argument"
