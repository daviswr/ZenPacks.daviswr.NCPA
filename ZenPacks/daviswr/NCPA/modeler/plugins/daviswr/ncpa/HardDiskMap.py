__doc__ = """
Models physical storage volumes using the Nagios Cross-Platform Agent
"""

import re
import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin

from ZenPacks.daviswr.NCPA.lib import ncpaUtil


class HardDiskMap(PythonPlugin):
    """ Nagios Cross-Platform Agent physical storage modeler plugin """

    maptype = 'HardDiskMap'
    compname = 'hw'
    relname = 'harddisks'
    modname = 'Products.ZenModel.HardDisk'

    deviceProperties = PythonPlugin.deviceProperties + (
        'zNcpaToken',
        'zNcpaPort',
        'zHardDiskMapMatch',
        )

    @inlineCallbacks
    def collect(self, device, log):
        """ Asynchronously collect data from device. Return a deferred. """
        log.info("%s: collecting physical storage data", device.id)

        token = getattr(device, 'zNcpaToken', None)

        if not token:
            log.error('%s: zNcpaToken not set', device.id)
            returnValue(None)

        url = ncpaUtil.build_url(
            host=device.manageIp,
            port=getattr(device, 'zNcpaPort', '5693'),
            token=token,
            endpoint='disk/physical'
            )

        log.debug(
            '%s: using NCPA phys disk URL %s',
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

        if 'physical' not in results or not results['physical']:
            log.error('Unable to get physical storage for %s', device.id)
            return None

        harddisk_re = getattr(device, 'zHardDiskMapMatch', '')
        if harddisk_re:
            log.debug(
                '%s: zHardDiskMapMatch set to %s',
                device.id,
                harddisk_re
                )
        else:
            log.debug('%s: zHardDiskMapMatch not set', device.id)

        rm = self.relMap()

        for volume in results['physical']:
            ignore = False
            if harddisk_re and not re.search(harddisk_re, volume):
                log.info(
                    '%s: %s ignored due to zHardDiskMapMatch',
                    device.id,
                    volume
                    )
                ignore = True
            else:
                log.debug('%s: Found storage %s', device.id, volume)

            if not ignore:
                om = self.objectMap()
                om.title = volume
                om.id = self.prepId(volume)
                rm.append(om)

        log.debug('%s RelMap:\n%s', self.name(), str(rm))
        return rm
