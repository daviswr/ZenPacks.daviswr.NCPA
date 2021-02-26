__doc__ = """
Models device-level attributes using the Nagios Cross-Platform Agent
"""

import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import MultiArgs, ObjectMap

from ZenPacks.daviswr.NCPA.lib import ncpaUtil


class DeviceMap(PythonPlugin):
    """ Nagios Cross-Platform Agent device modeler plugin """

    deviceProperties = PythonPlugin.deviceProperties + (
        'zNcpaToken',
        'zNcpaPort',
        )

    @inlineCallbacks
    def collect(self, device, log):
        """ Asynchronously collect data from device. Return a deferred. """
        log.info("%s: collecting device data", device.id)

        token = getattr(device, 'zNcpaToken', None)

        if not token:
            log.error('%s: zNcpaToken not set', device.id)
            returnValue(None)

        url = ncpaUtil.build_url(
            host=device.manageIp,
            port=getattr(device, 'zNcpaPort', '5693'),
            token=token,
            )

        log.debug('%s: using NCPA API URL %s', device.id, url.split('=')[0])

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
            else:
                output = output.get('root', output)

        except Exception, err:
            log.error('%s: %s', device.id, err)
            returnValue(None)

        returnValue(output)

    def process(self, device, results, log):
        """ Process results. Return iterable of datamaps or None. """

        vendors = {
            'AIX': 'IBM',
            'Darwin': 'Apple',
            'Linux': 'GNU',
            'Windows': 'Microsoft'
            }

        maps = list()
        device = dict()

        device['snmpSysName'] = results.get('system', {}).get('node', '')
        platform = results.get('system', {}).get('system', '')
        sw_ver = results.get('system', {}).get('release', '')

        device['setHWProductKey'] = MultiArgs(
            platform if platform else 'NCPA',
            'Nagios',
            )

        if platform and sw_ver:
            sw_ver = '{0} {1}'.format(platform, sw_ver)

        if 'uek' in sw_ver.lower():
            sw_vendor = 'Oracle'
        elif 'el' in sw_ver.lower():
            sw_vendor = 'RedHat'
        elif 'mac' in platform.lower():
            sw_vendor = 'Apple'
        else:
            sw_vendor = vendors.get(platform, 'Unknown')

        device['setOSProductKey'] = MultiArgs(sw_ver, sw_vendor)

        if 'Windows' == platform:
            # Example:
            # Hardware: Intel64 Family 6 Model 44 Stepping 2 AT/AT COMPATIBLE \
            # - Software: Windows Version 6.3 (Build 19042 Multiprocessor Free)
            device['snmpDescr'] = 'Hardware {0} - Software Windows'.format(
                results.get('system', {}).get('processor', '').split(',')[0]
                )
            device['snmpDescr'] += ' Version {0} (Build {1})'.format(
                results.get('system', {}).get('release', ''),
                results.get('system', {}).get('version', '').split('.')[-1],
                )
        else:
            # Example:
            # Linux localhost.localdomain 4.1.12-124.48.3.1.el6uek.x86_64 #2 \
            # SMP Fri Feb 12 10:08:08 PST 2021 x86_64
            device['snmpDescr'] = '{0} {1} {2} {3} {4}'.format(
                platform,
                device['snmpSysName'],
                results.get('system', {}).get('release', ''),
                results.get('system', {}).get('version', ''),
                results.get('system', {}).get('machine', '')
                )

        # modname='Products.ZenModel.Device' seems to be implicit
        maps.append(ObjectMap(data=device))

        mem = results.get('memory', {}).get('virtual', {}).get(
            'total',
            [0, '']
            )
        mem_value, mem_unit = mem
        mem_total = ncpaUtil.get_unit_value(mem_value, mem_unit)
        maps.append(ObjectMap(data={'totalMemory': mem_total}, compname='hw'))

        swap = results.get('memory', {}).get('swap', {}).get('total', [0, ''])
        swap_value, swap_unit = swap
        swap_total = ncpaUtil.get_unit_value(swap_value, swap_unit)
        maps.append(ObjectMap(
            data={'totalSwap': swap_total, 'uname': platform},
            compname='os'
            ))

        log.debug('%s ObjMaps:\n%s', self.name(), str(maps))

        return maps
