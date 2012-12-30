import cherrypy

def auth_members(users=[]):
    user = cherrypy.request.login.split("@")[0].upper()
    if user not in users:
        raise cherrypy.HTTPError("401 Unauthorized")

cherrypy.tools.auth_members = cherrypy.Tool('before_request_body', auth_members)
