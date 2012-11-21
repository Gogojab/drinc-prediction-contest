import cherrypy

##
# The base application class.
#
# This handles the mounting of pages to URLs and application specific config.
# Applications are created by the Server, which will also call the setup() and build()
# methods.  Application developers are expected to overwrite these methods. Within
# the build() method application developers should just use the set_config() and
# add_page() methods and do any other setup they need, such as scheduling tasks in the
# setup() method.
#

class Application:
    ##
    # Initialization
    #
    # @param root_url    The root url to mount pages onto.
    # @param cwd           The directory of the application.
    #
    def __init__(self, root_url="", cwd=""):
        self.root_url = root_url
        self.cwd = cwd
        self.conf = {}

    ##
    # Set application specific config
    #
    # @param conf    A CherryPy configuration file
    #
    def set_config(self, conf):
        self.conf = conf
        # This a work around to set the global app configuration, there is probably a CherryPy
        # command we can use in place here, but after a couple of hours looking I couldn't make any
        # progress and this solution seems to work.
        self.add_page("/", None, conf);

    ##
    # Mount a page onto a url with some page specific configuration
    #
    # @param url      The URL extension of the base URL to mount the page to
    # @param page    An instance of the class to be mounted on this url
    # @param conf    A CherryPy configuration file
    def add_page(self, url, page, conf={}):
        app = cherrypy.tree.mount(page, self.root_url + url)
        app.merge(self.conf)
        app.merge(conf)

    ##
    # Build the URL structure of the application, this function must be overridden.
    #
    def build(self):
        raise NameError("No build method defined")

    ##
    # Setup application specific tasks, this function may be overridden, if required.
    #
    def setup(self):
        pass
