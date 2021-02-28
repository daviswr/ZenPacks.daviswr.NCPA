__doc__ = """
Models services using the Nagios Cross-Platform Agent
"""

import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin

from ZenPacks.daviswr.NCPA.lib import ncpaUtil


class ServiceMap(PythonPlugin):
    """ Nagios Cross-Platform Agent service modeler plugin """

    relname = 'ncpaServices'
    modname = 'ZenPacks.daviswr.NCPA.Service'

    deviceProperties = PythonPlugin.deviceProperties + (
        'zNcpaToken',
        'zNcpaPort',
        'zNcpaServicesExpectedRunning',
        'zNcpaServicesExpectedStopped',
        'zNcpaServicesIgnored',
        )

    @inlineCallbacks
    def collect(self, device, log):
        """ Asynchronously collect data from device. Return a deferred. """
        log.info('%s: collecting services', device.id)

        token = getattr(device, 'zNcpaToken', None)

        if not token:
            log.error('%s: zNcpaToken not set', device.id)
            returnValue(None)

        url = ncpaUtil.build_url(
            host=device.manageIp,
            port=getattr(device, 'zNcpaPort', 5693),
            token=token,
            endpoint='services',
            )

        log.debug(
            '%s: using NCPA services URL %s', device.id,
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

        if 'services' not in results or not results['services']:
            log.error('Unable to get services for %s', device.id)
            return None

        states = {'running': 0, 'stopped': 1, 'unknown': 2}

        run_list = getattr(device, 'zNcpaServicesExpectedRunning', [])
        stop_list = getattr(device, 'zNcpaServicesExpectedStopped', [])
        ignore_list = getattr(device, 'zNcpaServicesIgnored', [])

        if run_list:
            log.debug(
                '%s: zNcpaServicesExpectedRunning set to %s',
                device.id,
                str(run_list)
                )
        else:
            log.debug('%s: zNcpaServicesExpectedRunning not set', device.id)

        if stop_list:
            log.debug(
                '%s: zNcpaServicesExpectedStopped set to %s',
                device.id,
                str(stop_list)
                )
        else:
            log.debug('%s: zNcpaServicesExpectedStopped not set', device.id)

        if ignore_list:
            log.debug(
                '%s: zNcpaServicesIgnored set to %s',
                device.id,
                str(ignore_list)
                )
        else:
            log.debug('%s: zNcpaServicesIgnored not set', device.id)

        rm = self.relMap()

        for service in results['services']:
            expected = states['unknown']
            if service in ignore_list:
                log.info(
                    '%s: %s ignored due to zNcpaServicesIgnored',
                    device.id,
                    service
                    )
                ignore = True
            elif run_list and service in run_list:
                ignore = False
                expected = states['running']
            elif stop_list and service in stop_list:
                ignore = False
                expected = states['stopped']
            else:
                ignore = True
                log.debug('%s: Service %s ignored ', device.id, service)

            if not ignore:
                log.debug('%s: Found service %s', device.id, service)
                om = self.objectMap()
                om.expectedState = expected
                # om.serviceName = service
                # om.startName = service
                om.id = self.prepId(service)
                rm.append(om)

        log.debug('%s RelMap:\n%s', self.name(), str(rm))
        return rm
