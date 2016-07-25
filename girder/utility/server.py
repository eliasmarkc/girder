#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright Kitware Inc.
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

import cherrypy
import mimetypes
import os
import six

import girder.events
from girder import constants, logprint
from girder.utility import plugin_utilities, model_importer
from girder.utility.plugin_utilities import _plugin_webroots  # noqa
from girder.utility import config
from . import webroot


def configureServer(test=False, plugins=None, curConfig=None):
    """
    Function to setup the cherrypy server. It configures it, but does
    not actually start it.

    :param test: Set to True when running in the tests.
    :type test: bool
    :param plugins: If you wish to start the server with a custom set of
                    plugins, pass this as a list of plugins to load. Otherwise,
                    will use the PLUGINS_ENABLED setting value from the db.
    :param curConfig: The configuration dictionary to update.
    """
    if curConfig is None:
        curConfig = config.getConfig()

    curStaticRoot = constants.STATIC_ROOT_DIR

    appconf = {
        '/': {
            'request.dispatch': cherrypy.dispatch.MethodDispatcher(),
            'tools.staticdir.root': curStaticRoot,
            'request.show_tracebacks': test,
            'request.methods_with_bodies': ('POST', 'PUT', 'PATCH')
        },
        '/static': {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': 'clients/web/static'
        }
    }
    # Add MIME types for serving Fontello files from staticdir;
    # these may be missing or incorrect in the OS
    mimetypes.add_type('application/vnd.ms-fontobject', '.eot')
    mimetypes.add_type('application/x-font-ttf', '.ttf')
    mimetypes.add_type('application/font-woff', '.woff')

    if test:
        appconf['/src'] = {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': 'clients/web/src',
        }
        appconf['/test'] = {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': 'clients/web/test',
        }
        appconf['/clients'] = {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': 'clients'
        }
        appconf['/plugins'] = {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': 'plugins',
        }

    curConfig.update(appconf)

    if test:
        # Force some config params in testing mode
        curConfig.update({'server': {
            'mode': 'testing',
            'api_root': 'api/v1',
            'static_root': 'static',
            'api_static_root': '../static'
        }})

    mode = curConfig['server']['mode'].lower()
    logprint.info('Running in mode: ' + mode)
    cherrypy.config['engine.autoreload.on'] = mode == 'development'

    # Don't import this until after the configs have been read; some module
    # initialization code requires the configuration to be set up.
    from girder.api import api_main

    root = webroot.Webroot()
    api_main.addApiToNode(root)

    cherrypy.engine.subscribe('start', girder.events.daemon.start)
    cherrypy.engine.subscribe('stop', girder.events.daemon.stop)

    if plugins is None:
        settings = model_importer.ModelImporter().model('setting')
        plugins = settings.get(constants.SettingKey.PLUGINS_ENABLED, default=())

    plugins = list(plugin_utilities.getToposortedPlugins(plugins, ignoreMissing=True))
    root.updateHtmlVars({
        'apiRoot': curConfig['server']['api_root'],
        'staticRoot': curConfig['server']['static_root'],
        'plugins': plugins
    })

    apiStaticRoot = curConfig['server'].get('api_static_root', '')
    if not apiStaticRoot:
        apiStaticRoot = curConfig['server']['static_root']
    root.api.v1.updateHtmlVars({
        'apiRoot': curConfig['server']['api_root'],
        'staticRoot': apiStaticRoot,
    })

    root, appconf, _ = plugin_utilities.loadPlugins(
        plugins, root, appconf, root.api.v1, buildDag=False)

    return root, appconf


def loadRouteTable():
    """
    Retrieves the route table from Girder and reconciles the state of it with the current
    application state.

    Reconciliation deals with 2 scenarios:
    1) A plugin is no longer active (by being disabled or removed) and the route for the
    plugin needs to be removed.
    2) A webroot was added (a new plugin was enabled) and a default route needs to be added.

    :returns: The non empty routes (as a dict of name -> route) to be mounted by CherryPy
    during Girder's setup phase.
    """
    global _plugin_webroots
    setting = model_importer.ModelImporter().model('setting')

    def reconcileRouteTable(routeTable):
        hasChanged = False

        # 'girder' is a special route, which can't be removed
        for name in routeTable.keys():
            if name != 'girder' and name not in _plugin_webroots:
                del routeTable[name]
                hasChanged = True

        for name in _plugin_webroots.keys():
            if name not in routeTable:
                routeTable[name] = os.path.join('/', name)
                hasChanged = True

        if hasChanged:
            setting.set(constants.SettingKey.ROUTE_TABLE, routeTable)

        return routeTable

    routeTable = reconcileRouteTable(setting.get(constants.SettingKey.ROUTE_TABLE))

    return {name: route for (name, route) in six.viewitems(routeTable) if route}


def setup(test=False, plugins=None, curConfig=None):
    """
    Configure and mount the Girder server and plugins under the
    appropriate routes.

    See ROUTE_TABLE setting.

    :param test: Whether to start in test mode.
    :param plugins: List of plugins to enable.
    :param curConfig: The config object to update.
    """
    global _plugin_webroots
    girderWebroot, appconf = configureServer(test, plugins, curConfig)
    routeTable = loadRouteTable()

    # Mount Girder
    application = cherrypy.tree.mount(girderWebroot, routeTable['girder'], appconf)

    # Mount everything else in the routeTable
    for (name, route) in six.viewitems(routeTable):
        if name != 'girder' and name in _plugin_webroots:
            cherrypy.tree.mount(_plugin_webroots[name], route, appconf)

    if test:
        application.merge({'server': {'mode': 'testing'}})

    return application


class _StaticFileRoute(object):
    exposed = True

    def __init__(self, path, contentType=None):
        self.path = os.path.abspath(path)
        self.contentType = contentType

    def GET(self):
        return cherrypy.lib.static.serve_file(self.path,
                                              content_type=self.contentType)


def staticFile(path, contentType=None):
    """
    Helper function to serve a static file. This should be bound as the route
    object, i.e. info['serverRoot'].route_name = staticFile('...')

    :param path: The path of the static file to serve from this route.
    :type path: str
    :param contentType: The MIME type of the static file. If set to None, the
                        content type wll be guessed by the file extension of
                        the 'path' argument.
    """
    return _StaticFileRoute(path, contentType)
