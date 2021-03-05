__doc__ = """
Models processes using the Nagios Cross-Platform Agent
"""

import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.ZenModel.OSProcessMatcher import buildObjectMapData

from ZenPacks.daviswr.NCPA.lib import ncpaUtil


class ProcessMap(PythonPlugin):
    """ Nagios Cross-Platform Agent processes modeler plugin """

    maptype = 'OSProcessMap'
    compname = 'os'
    relname = 'processes'
    modname = 'Products.ZenModel.OSProcess'

    deviceProperties = PythonPlugin.deviceProperties + (
        'osProcessClassMatchData',
        'zNcpaToken',
        'zNcpaPort',
        )

    @inlineCallbacks
    def collect(self, device, log):
        """ Asynchronously collect data from device. Return a deferred. """
        log.info('%s: collecting processes', device.id)

        token = getattr(device, 'zNcpaToken', None)

        if not token:
            log.error('%s: zNcpaToken not set', device.id)
            returnValue(None)

        url = ncpaUtil.build_url(
            host=device.manageIp,
            port=getattr(device, 'zNcpaPort', 5693),
            token=token,
            endpoint='processes',
            )

        log.debug(
            '%s: using NCPA processes URL %s', device.id,
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

        if 'processes' not in results or not results['processes']:
            log.error('Unable to get processes for %s', device.id)
            return None

        match_data = device.osProcessClassMatchData
        cmds = list()
        for proc in results['processes']:
            cmd = proc.get('cmd', '') or proc.get('exe', '')
            cmd = proc.get('name') if 'Unknown' == cmd or not cmd else cmd
            cmd = cmd.strip()
            if cmd:
                log.debug(
                    '%s: %s\tprocess: %s',
                    device.id,
                    proc.get('pid', ''),
                    cmd
                    )
                cmds.append(cmd)
            else:
                log.warn('Skipping process with no name')

        rm = self.relMap()
        rm.extend(map(self.objectMap, buildObjectMapData(match_data, cmds)))
        log.debug('%s RelMap:\n%s', self.name(), str(rm))
        return rm
