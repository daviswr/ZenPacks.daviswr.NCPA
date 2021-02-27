__doc__ = """
Models network interfaces using the Nagios Cross-Platform Agent
"""

import re
import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin

from ZenPacks.daviswr.NCPA.lib import ncpaUtil


class InterfaceMap(PythonPlugin):
    """ Nagios Cross-Platform Agent interface modeler plugin """

    maptype = 'InterfaceMap'
    compname = 'os'
    relname = 'interfaces'
    modname = 'Products.ZenModel.IpInterface'

    deviceProperties = PythonPlugin.deviceProperties + (
        'zNcpaToken',
        'zNcpaPort',
        'zInterfaceMapIgnoreNames',
        )

    @inlineCallbacks
    def collect(self, device, log):
        """ Asynchronously collect data from device. Return a deferred. """
        log.info('%s: collecting interfaces', device.id)

        token = getattr(device, 'zNcpaToken', None)

        if not token:
            log.error('%s: zNcpaToken not set', device.id)
            returnValue(None)

        url = ncpaUtil.build_url(
            host=device.manageIp,
            port=getattr(device, 'zNcpaPort', 5693),
            token=token,
            endpoint='interface'
            )

        log.debug(
            '%s: using NCPA interface URL %s',
            device.id,
            url.split('=')[0]
            )

        try:
            response = yield getPage(url, method='GET')
            output = json.loads(response)

            if 'error' in output:
                log.error(
                    '%s: %s',
                    device.id,
                    output['error'].get('message', output['error'])
                    )
                returnValue(None)

        except Exception, err:
            log.error('%s: %s', device.id, err)
            returnValue(None)

        returnValue(output)

    def process(self, device, results, log):
        """ Process results. Return iterable of datamaps or None. """

        if 'interface' not in results or not results['interface']:
            log.error('Unable to get interfaces for %s', device.id)
            return None

        ignore_re = getattr(device, 'zInterfaceMapIgnoreNames', '')
        if ignore_re:
            log.debug(
                '%s: zInterfaceMapIgnoreNames set to %s',
                device.id,
                ignore_re
                )
        else:
            log.debug('%s: zInterfaceMapIgnoreNames not set', device.id)

        rm = self.relMap()

        for interface in results['interface']:
            if ignore_re and re.search(ignore_re, interface):
                log.info(
                    '%s: %s ignored due to zInterfaceMapIgnoreNames',
                    device.id,
                    interface
                    )
            else:
                log.debug('%s: Found interface %s', device.id, interface)
                om = self.objectMap()
                om.interfaceName = interface
                # NCPA doesn't report if interface is up or down
                om.adminStatus = 1
                om.operStatus = 1
                om.type = 'ethernetCsmacd'
                om.title = interface
                om.id = self.prepId(interface)
                rm.append(om)

        log.debug('%s RelMap:\n%s', self.name(), str(rm))
        return rm
