# Copyright (c) 2004-2011, CherryPy Team (team@cherrypy.org)
# Copyright (c) 2011, Hein-Pieter van Braam (hp@tmm.cx)
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright notice,
#       this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright notice,
#       this list of conditions and the following disclaimer in the documentation
#       and/or other materials provided with the distribution.
#     * Neither the name of the CherryPy Team nor the names of its contributors
#       may be used to endorse or promote products derived from this software
#       without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 
__author__ = 'Hein-Pieter van Braam'
__date__ = 'June 2011'
 
import binascii
from cherrypy._cpcompat import base64_decode
import kerberos
import cherrypy
import os
 
def multi_headers():
        cherrypy.response.header_list.extend(cherrypy.response.multiheaders)
 
def kerberos_auth(KRB5realm="AD.DATCON.CO.UK", HTTPrealm="DCL", service='HTTP', debug=False, keytab=None):
        """
        KRB5realm
                A string containing the Kerberos Realm to authenticate to
 
        HTTPrealm
                A string containing the HTTP realm to authenticate to
 
        service
                The service name for the server principal to use, defaults to 'HTTP'
 
        keytab
                Keytab file for the current program. This will override the environment
 
        debug
                Provide some debugging output
        """
       
        request = cherrypy.serving.request
 
        if '"' in HTTPrealm:
                raise ValueError('Realm cannot contain the " (quote) character.')
 
        auth_header = request.headers.get('authorization')
 
        if auth_header is not None:
                try:
                        scheme, params = auth_header.split(' ', 1)
                        if scheme.lower() == 'basic':
                                if debug:
                                        cherrypy.log('Attempting basic authentication', 'TOOLS.AUTH_KERBEROS')
                                username, password = base64_decode(params).split(':', 1)
 
                                try:
                                        kerberos.checkPassword(username, password, service, KRB5realm)
                                        if debug:
                                                cherrypy.log('Basic auth successful', 'TOOLS.AUTH_KERBEROS')
                                        request.login = username + "@" + KRB5realm
                                        return # successful authentication
 
                                except:
                                        if debug:
                                                cherrypy.log('Basic auth failed', 'TOOLS.AUTH_KERBEROS')
                                        pass
 
                        if scheme.lower() == 'negotiate':
                                if debug:
                                        cherrypy.log('Attempting negotiate authentication', 'TOOLS.AUTH_KERBEROS')
 
                                if keytab is not None:
                                        if debug:
                                                cherrypy.log('Using keytab %s' % keytab, 'TOOLS.AUTH_KERBEROS')
                                        os.environ["KRB5_KTNAME"] = keytab
 
                                result, context = kerberos.authGSSServerInit(service)
                                if result != 1:
                                        raise cherrypy.HTTPError(500, "GSS API failure")
                               
                                gssstring=""
                                result = kerberos.authGSSServerStep(context, params)
                                if result == kerberos.AUTH_GSS_COMPLETE:
                                        if debug:
                                                cherrypy.log('Negotiate auth successful', 'TOOLS.AUTH_KERBEROS')
 
                                        gssstring = kerberos.authGSSServerResponse(context)
                                        cherrypy.serving.response.headers['www-authenticate'] = 'Negotiate %s' % gssstring
                                        request.login = kerberos.authGSSServerUserName(context)
                                        kerberos.authGSSServerClean(context)
                                        return # successful authentication
 
                except (ValueError, binascii.Error): # split() error, base64.decodestring() error
                        raise cherrypy.HTTPError(400, 'Bad Request')
       
        # Respond with 401 status and a WWW-Authenticate header
        cherrypy.request.hooks.attach('on_end_resource', multi_headers);
        cherrypy.serving.response.multiheaders = [('www-authenticate', 'Negotiate'), ('www-authenticate', 'Basic realm="%s"' % HTTPrealm)]
 
        raise cherrypy.HTTPError(401, "You are not authorized to access that resource")
 
cherrypy.tools.auth_kerberos = cherrypy.Tool('before_request_body', kerberos_auth)
