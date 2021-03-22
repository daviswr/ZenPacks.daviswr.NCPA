__doc__ = """NcpaPluginDataSource
Datasource for remote Nagios plugin via NCPA
"""

import logging
LOG = logging.getLogger('zen.NcpaPlugin')

import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage
from zope.interface import implements

from Products.ZenEvents import Event
from Products.ZenEvents.ZenEventClasses import Status_Nagios
from Products.Zuul.form import schema
from Products.Zuul.infos import ProxyProperty
from Products.Zuul.infos.template import RRDDataSourceInfo
from Products.Zuul.interfaces import IRRDDataSourceInfo
from Products.Zuul.utils import ZuulMessageFactory as _t
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import (
    PythonDataSource,
    PythonDataSourcePlugin
    )

from ZenPacks.daviswr.NCPA.dsplugins.Processes import send_to_debug
from ZenPacks.daviswr.NCPA.lib import ncpaUtil
from ZenPacks.daviswr.NCPA.lib.exceptions import NcpaError


class NcpaPluginDataSource(PythonDataSource):
    NCPA_PLUGIN = 'NcpaPlugin'
    ZENPACKID = 'ZenPacks.daviswr.NCPA'
    sourcetypes = (NCPA_PLUGIN, )
    sourcetype = NCPA_PLUGIN
    plugin_classname = (
        ZENPACKID + '.datasources.NcpaPluginDataSource.NcpaPluginDataSourcePlugin'  # noqa
        )
    eventClass = Status_Nagios

    ipAddress = '${dev/manageIp}'
    port = 5693
    token = '${dev/zNcpaToken}'
    pluginName = ''
    pluginArgs = ''
    _properties = PythonDataSource._properties + (
        {'id': 'ipAddress', 'type': 'string', 'mode': 'w'},
        {'id': 'port', 'type': 'int', 'mode': 'w'},
        {'id': 'pluginName', 'type': 'string', 'mode': 'w'},
        {'id': 'pluginArgs', 'type': 'string', 'mode': 'w'},
        {'id': 'token', 'type': 'string', 'mode': 'w'},
        )


class NcpaPluginDataSourcePlugin(PythonDataSourcePlugin):
    @classmethod
    def params(cls, datasource, context):
        params = {
            'ipAddress': datasource.talesEval(datasource.ipAddress, context),
            'port': datasource.talesEval(datasource.port, context),
            'token': datasource.talesEval(datasource.token, context),
            'pluginName': datasource.talesEval(datasource.pluginName, context),
            'pluginArgs': datasource.talesEval(datasource.pluginArgs, context),
            'eventKey': datasource.talesEval(datasource.eventKey, context),
            'eventClass': datasource.talesEval(datasource.eventClass, context),
            }

        return params

    @inlineCallbacks
    def collect(self, config):
        ip_addr = config.datasources[0].params.get('ipAddress', '')
        token = config.datasources[0].params.get('token', '')
        port = int(config.datasources[0].params.get('port', 5693))
        plugin_name = config.datasources[0].params.get('pluginName', '')
        plugin_args = config.datasources[0].params.get('pluginArgs', '')
        err_str = ''

        if not ip_addr:
            err_str = 'No IP address or hostname'
        elif not token:
            err_str = 'zNcpaToken not set'
        elif not plugin_name:
            err_str = 'No NCPA plugin specified'

        if err_str:
            LOG.error('%s: %s', config.id, err_str)
            raise NcpaError(err_str)

        LOG.debug('%s: Collecting from NCPA client %s', config.id, ip_addr)

        url = ncpaUtil.build_url(
            host=ip_addr,
            port=port,
            token=token,
            endpoint='plugins/{0}'.format(plugin_name),
            params={'args': plugin_args}
            )

        LOG.debug(
            '%s: NCPA plugin URL (token omitted): %s',
            config.id,
            url.replace(token, '')
            )

        response = yield getPage(url, method='GET')
        output = json.loads(response)

        LOG.debug('%s: NCPA API output:\n%s', config.id, str(output))
        # This will raise an exception if necessary
        ncpaUtil.error_check(output, config.id, LOG)
        returnValue(output)

    def onSuccess(self, results, config):
        plugin_name = config.datasources[0].params.get('pluginName', '')
        event_key = config.datasources[0].params.get('eventKey', 'NcpaPlugin')
        event_class = config.datasources[0].params.get(
            'eventClass',
            Status_Nagios
            )
        data = self.new_data()

        returncode = int(results.get('returncode', -1))
        stdout = results.get('stdout', '')

        state, severity, values = ncpaUtil.parse_nagios(stdout)
        values['returncode'] = returncode

        for datasource in config.datasources:
            comp = datasource.component
            for datapoint in datasource.points:
                if datapoint.id in values:
                    value = values[datapoint.id]
                    data['values'][comp][datapoint.dpName] = (value, 'N')

        data['events'].append({
            'device': config.id,
            'severity': severity,
            'eventKey': event_key,
            'eventClass': event_class,
            'component': plugin_name,
            'summary': state,
            })

        return data

    def onError(self, error, config):
        plugin_name = config.datasources[0].params.get('pluginName', '')
        event_key = config.datasources[0].params.get('eventKey', 'NcpaPlugin')
        event_class = config.datasources[0].params.get(
            'eventClass',
            Status_Nagios
            )
        data = self.new_data()

        msg = '{0} NCPA plugin execution error: {1}'.format(
            config.id,
            error.value
            )
        if send_to_debug(error):
            LOG.debug(msg)
        else:
            LOG.error(msg)

        data['events'].append({
            'device': config.id,
            'severity': Event.Error,
            'eventKey': event_key,
            'eventClass': event_class,
            'component': plugin_name,
            'summary': 'NCPA plugin execution error: {0}'.format(error.value),
            })

        return data


class INcpaPluginDataSourceInfo(IRRDDataSourceInfo):
    cycletime = schema.TextLine(title=_t(u'Cycle Time (seconds)'))
    ipAddress = schema.TextLine(
        title=_t(u'Hostname or IP Address'),
        group=_t('NCPA Plugin')
        )
    port = schema.Int(title=_t(u'Port'), group=_t('NCPA Plugin'))
    pluginName = schema.TextLine(
        title=_t(u'Plugin Name'),
        group=_t('NCPA Plugin')
        )
    pluginArgs = schema.TextLine(
        title=_t(u'Plugin Arguments'),
        group=_t('NCPA Plugin')
        )
    token = schema.TextLine(title=_t(u'Token'), group=_t('NCPA Plugin'))


class NcpaPluginDataSourceInfo(RRDDataSourceInfo):
    implements(INcpaPluginDataSourceInfo)
    cycletime = ProxyProperty('cycletime')
    ipAddress = ProxyProperty('ipAddress')
    port = ProxyProperty('port')
    pluginName = ProxyProperty('pluginName')
    pluginArgs = ProxyProperty('pluginArgs')
    token = ProxyProperty('token')

    @property
    def testable(self):
        """ Unknown how to make the test work yet """
        return False
