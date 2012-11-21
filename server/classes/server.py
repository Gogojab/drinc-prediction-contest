import os, sys, cherrypy, logging
from cherrypy import _cplogging
from logging import handlers
from cherrypy.process.plugins import Daemonizer
from cherrypy.process.plugins import PIDFile
import tools.auth_kerberos
import tools.auth_members

##
# This class handles setting the server CherryPy config, loading in the applications, and
# starting the CherryPy server.
#
class Server:
    ##
    # Initialization
    #
    # @param root_dir    The root directory of the server i.e. where the control.py
    #                             script is placed.
    # @param apps          The list of applications to run.
    # @param conf          The configuration file to use.
    # @param daemon       Whether to run as a daemon or not, True or False.
    #
    def __init__(self, root_dir, apps, conf, daemon=True):
        self.root_dir = root_dir
        self.apps = apps
        self.conf = conf
        self.daemon = daemon

    ##
    # Sets the config, loads in the apps and starts the server.
    #
    def start(self):
        cherrypy.config.update(self.root_dir + "/conf/" + self.conf)

        # Store the PID so we can stop the server if required.
        PIDFile(cherrypy.engine, self.root_dir + "/pid").subscribe()

        if (self.daemon):
            Daemonizer(cherrypy.engine).subscribe()

        app_instances = []
        for app in self.apps:
            # Load the module
            __import__("apps." + app)
            module = sys.modules["apps." + app + ".app"]

            # Get the class name
            try:
                app_class_name = getattr(module, "application_class_name")
            except AttributeError:
                print "No class name defined"

            # Create an instance of the class, call and build()
            try:
                AppClass = getattr(module, app_class_name)
            except AttributeError:
                print "Couldn't find application class: " + app
            else:
                extension = app.replace(".", "/")
                app_instance = AppClass("/" + extension, self.root_dir + "/apps/" + extension)
                app_instance.build()
                app_instances.append(app_instance)

        # Remove the default FileHandlers if present.
        log = cherrypy.log
        log.error_file = ""
        log.access_file = ""

        maxBytes = getattr(log, "rot_maxBytes", 10000000)
        backupCount = getattr(log, "rot_backupCount", 1000)

        # Make sure we have a directory to put the logs in.
        if not os.path.exists("logs"):
            os.makedirs("logs")

        # Make a new RotatingFileHandler for the error log.
        fname = getattr(log, "rot_error_file", "logs/error.log")
        h = handlers.RotatingFileHandler(fname, 'a', maxBytes, backupCount)
        h.setLevel(logging.DEBUG)
        h.setFormatter(_cplogging.logfmt)
        log.error_log.addHandler(h)

        # Make a new RotatingFileHandler for the access log.
        fname = getattr(log, "rot_access_file", "logs/access.log")
        h = handlers.RotatingFileHandler(fname, 'a', maxBytes, backupCount)
        h.setLevel(logging.DEBUG)
        h.setFormatter(_cplogging.logfmt)
        log.access_log.addHandler(h)

        # Start the server, must be called after the applications are built.
        cherrypy.engine.start()

        # Setup up the applications, this must be called after daemonization or we have threading issues.
        for app_instance in app_instances:
            app_instance.setup()

        cherrypy.engine.block()
