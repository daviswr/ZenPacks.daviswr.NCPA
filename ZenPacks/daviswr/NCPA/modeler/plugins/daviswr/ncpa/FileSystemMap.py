__doc__ = """
Models filesystems using the Nagios Cross-Platform Agent
"""

import re
import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin

from ZenPacks.daviswr.NCPA.lib import ncpaUtil


class FileSystemMap(PythonPlugin):
    """ Nagios Cross-Platform Agent filesystem modeler plugin """

    maptype = 'FileSystemMap'
    compname = 'os'
    relname = 'filesystems'
    modname = 'Products.ZenModel.FileSystem'

    deviceProperties = PythonPlugin.deviceProperties + (
        'zNcpaToken',
        'zNcpaPort',
        'zFileSystemMapIgnoreNames',
        'zFileSystemMapIgnoreTypes',
        )

    @inlineCallbacks
    def collect(self, device, log):
        """ Asynchronously collect data from device. Return a deferred. """
        log.info('%s: collecting filesystems', device.id)

        token = getattr(device, 'zNcpaToken', None)

        if not token:
            log.error('%s: zNcpaToken not set', device.id)
            returnValue(None)

        url = ncpaUtil.build_url(
            host=device.manageIp,
            port=getattr(device, 'zNcpaPort', 5693),
            token=token,
            endpoint='disk/logical'
            )

        log.debug(
            '%s: using NCPA filesystem URL %s',
            device.id,
            url.split('=')[0]
            )

        try:
            response = yield getPage(url, method='GET')
            output = json.loads(response)

            if 'error' in output:
                error = output['error']
                err_str = error.get('message', 'an unknown error occurred') \
                    if isinstance(error, dict) else str(error)
                log.error('%s: %s', device.id, error)
                returnValue(None)

        except Exception, err:
            log.error('%s: %s', device.id, err)
            returnValue(None)

        returnValue(output)

    def process(self, device, results, log):
        """ Process results. Return iterable of datamaps or None. """

        if 'logical' not in results or not results['logical']:
            log.error('Unable to get filesystems for %s', device.id)
            return None

        ignore_re = getattr(device, 'zFileSystemMapIgnoreNames', '')
        if ignore_re:
            log.debug(
                '%s: zFileSystemMapIgnoreNames set to %s',
                device.id,
                ignore_re
                )
        else:
            log.debug('%s: zFileSystemMapIgnoreNames not set', device.id)

        ignore_list = getattr(device, 'zFileSystemMapIgnoreTypes', [])
        if ignore_list:
            log.debug(
                '%s: zFileSystemMapIgnoreTypes set to %s',
                device.id,
                str(ignore_list)
                )
        else:
            log.debug('%s: zFileSystemMapIgnoreTypes not set', device.id)

        rm = self.relMap()

        for filesystem in results['logical']:
            fs_dict = results['logical'][filesystem]
            replace_char = '/' if filesystem.startswith('|') else ''
            path = filesystem.replace('|', replace_char)
            ignore = False
            if ignore_re and re.search(ignore_re, path):
                log.info(
                    '%s: %s ignored due to zFileSystemMapIgnoreNames',
                    device.id,
                    path
                    )
                ignore = True
            else:
                for fs_type in ignore_list:
                    if fs_type in fs_dict.get('opts', ''):
                        log.info(
                            '%s: %s ignored due to zFileSystemMapIgnoreTypes',
                            device.id,
                            path
                            )
                        ignore = True
                log.debug('%s: Found filesystem %s', device.id, path)

            if not ignore:
                om = self.objectMap()
                om.mount = path
                om.storageDevice = fs_dict.get('device_name', '')[0]
                om.type = fs_dict.get('fstype', '')
                # NCPA does not return block size
                om.blockSize = 1
                fs_size, fs_unit = fs_dict.get('total', [0, ''])
                om.totalBlocks = ncpaUtil.get_unit_value(fs_size, fs_unit)
                om.title = path
                om.id = self.prepId(filesystem)
                rm.append(om)

        log.debug('%s RelMap:\n%s', self.name(), str(rm))
        return rm
