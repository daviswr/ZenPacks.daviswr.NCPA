__doc__ = """
Models processors using the Nagios Cross-Platform Agent
"""

import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import MultiArgs

from ZenPacks.daviswr.NCPA.lib import ncpaUtil


class CpuMap(PythonPlugin):
    """ Nagios Cross-Platform Agent CPU modeler plugin """

    maptype = 'CPUMap'
    compname = 'hw'
    relname = 'cpus'
    modname = 'Products.ZenModel.CPU'

    deviceProperties = PythonPlugin.deviceProperties + (
        'zNcpaToken',
        'zNcpaPort',
        )

    @inlineCallbacks
    def collect(self, device, log):
        """ Asynchronously collect data from device. Return a deferred. """
        log.info('%s: collecting processors', device.id)

        token = getattr(device, 'zNcpaToken', None)

        if not token:
            log.error('%s: zNcpaToken not set', device.id)
            returnValue(None)

        cpu_url = ncpaUtil.build_url(
            host=device.manageIp,
            port=getattr(device, 'zNcpaPort', 5693),
            token=token,
            endpoint='cpu/count'
            )

        sys_url = ncpaUtil.build_url(
            host=device.manageIp,
            port=getattr(device, 'zNcpaPort', 5693),
            token=token,
            endpoint='system/processor'
            )

        log.debug(
            '%s: using NCPA CPU URL %s',
            device.id,
            cpu_url.split('=')[0]
            )
        log.debug(
            '%s: using NCPA System URL %s',
            device.id,
            sys_url.split('=')[0]
            )

        try:
            response = yield getPage(cpu_url, method='GET')
            output = json.loads(response)

            response = yield getPage(sys_url, method='GET')
            output.update(json.loads(response))

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

        count = 0
        if len(results.get('count', [])) > 1:
            # Could be a list of cores per socket?
            sockets = results['count'][0]
            for socket in sockets:
                count += socket

        if 0 == count:
            log.error('Unable to get CPU core count for %s', device.id)
            return None

        # Linux just reports the architecture, like x86_64,
        # but Windows is a little more interesting:
        # Intel64 Family 6 Model 44 Stepping 2, GenuineIntel
        model = results.get('processor', '')
        if not model:
            log.warning('Unable to get CPU model for %s', device.id)
            model = 'CPU'

        # Can't clean up for everything but can make a few attempts
        if 'INTEL' in model.upper():
            mfg = 'Intel'
        elif 'AMD' in model.upper():
            mfg = 'AMD'
        elif ' ' in model:
            mfg = model.split(' ')[0]
        else:
            mfg = 'Unknown'

        # Processors
        rm = self.relMap()

        counter = 0
        socket_num = 0
        for socket in sockets:
            for core in range(0, socket):
                log.debug(
                    '%s: Found CPU %s - Socket %s Core %s',
                    device.id,
                    counter,
                    socket_num,
                    core
                    )
                om = self.objectMap()
                om.setProductKey = MultiArgs(model, mfg)
                om.socket = socket_num
                # To match zenoss.snmp.CpuMap
                om.id = self.prepId(counter)
                rm.append(om)
                counter += 1
            socket_num += 1

        log.debug('%s RelMap:\n%s', self.name(), str(rm))
        return rm
