#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright 2013 Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

from .. import base
from girder.constants import GIRDER_ROUTE_ID, GIRDER_STATIC_ROUTE_ID, SettingKey


def setUpModule():
    base.startServer()


def tearDownModule():
    base.stopServer()


class WebRootTestCase(base.TestCase):

    def testAccessWebRoot(self):
        """
        Requests the webroot and tests the existence of several
        elements in the returned html
        """
        resp = self.request(path='/', method='GET', isJson=False, prefix='')
        self.assertStatus(resp, 200)
        body = self.getBody(resp)
        self.assertTrue('girder_app.min.js' in body)
        self.assertTrue('girder_lib.min.js' in body)

        emailAddress = self.model('setting').get(SettingKey.CONTACT_EMAIL_ADDRESS)
        self.assertTrue('contactEmail: \'%s\'' % emailAddress in body)
        self.model('setting').set(SettingKey.CONTACT_EMAIL_ADDRESS, 'foo@bar.com')
        # A new request to update changes
        resp = self.request(path='/', method='GET', isJson=False, prefix='')
        self.assertStatus(resp, 200)
        body = self.getBody(resp)
        self.assertTrue('contactEmail: \'%s\'' % 'foo@bar.com' in body)

    def testWebRootProperlyHandlesStaticRouteUrls(self):
        self.model('setting').set(SettingKey.ROUTE_TABLE, {
            GIRDER_ROUTE_ID: '/',
            GIRDER_STATIC_ROUTE_ID: 'http://my-cdn-url.com/static'
        })

        resp = self.request(path='/', method='GET', isJson=False, prefix='')
        self.assertStatus(resp, 200)
        body = self.getBody(resp)

        self.assertTrue('href="http://my-cdn-url.com/static/img/Girder_Favicon.png"' in body)

        # Same assertion should hold true for Swagger
        resp = self.request(path='/', method='GET', isJson=False)
        self.assertStatus(resp, 200)
        body = self.getBody(resp)

        self.assertTrue('href="http://my-cdn-url.com/static/img/Girder_Favicon.png"' in body)
