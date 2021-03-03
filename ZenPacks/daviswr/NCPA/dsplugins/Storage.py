""" Monitors storage device NCPA metrics """

import logging
LOG = logging.getLogger('zen.NCPA')

import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import (
    PythonDataSourcePlugin
    )

from ZenPacks.daviswr.NCPA.lib import ncpaUtil


class Storage(PythonDataSourcePlugin):
    """ NCPA storage device data source plugin """

    @classmethod
    def config_key(cls, datasource, context):
        """ Return a tuple defining collection uniqueness. """
        return(
            context.device().id,
            datasource.getCycleTime(context),
            'disk-physical',
            )

    @classmethod
    def params(cls, datasource, context):
        """ Return params dictionary needed for this plugin. """
        return {
            'token': context.zNcpaToken,
            'port': context.zNcpaPort,
            }

    @inlineCallbacks
    def collect(self, config):
        data = self.new_data()
        ip_addr = config.manageIp or config.id
        # zProperties aren't going to change between datasources
        token = config.datasources[0].params.get('token', '')
        port = config.datasources[0].params.get('port', 5693)

        if not ip_addr:
            LOG.error('%s: No IP address or hostname', config.id)
            returnValue(None)
        elif not token:
            LOG.error('%s: zNcpaToken not set', config.id)
            returnValue(None)

        LOG.debug('%s: Collecting from NCPA client %s', config.id, ip_addr)

        url = ncpaUtil.build_url(
            host=ip_addr,
            port=port,
            token=token,
            endpoint='disk/physical'
            )

        try:
            response = yield getPage(url, method='GET')
            output = json.loads(response)
        except Exception, err:
            LOG.error('%s: %s', config.id, err)
            returnValue(None)

        LOG.debug(
            '%s: %s NCPA API output:\n%s',
            config.id,
            config.datasources[0],
            str(output)
            )

        disks = output.get('physical', dict())

        for datasource in config.datasources:
            LOG.debug(
                '%s: Component %s datasource %s',
                config.id,
                datasource.component,
                datasource.datasource
                )
            stats = dict()
            if datasource.component in disks:
                disk = disks[datasource.component]
                stats['read_count'] = disk['read_count'][0]
                stats['write_count'] = disk['write_count'][0]
                stats['read_bytes'] = ncpaUtil.get_unit_value(
                    disk['read_bytes'][0],
                    disk['read_bytes'][1]
                    )

                stats['write_bytes'] = ncpaUtil.get_unit_value(
                    disk['write_bytes'][0],
                    disk['write_bytes'][1]
                    )

            LOG.debug(
                '%s: %s NCPA metrics:\n%s',
                config.id,
                datasource.datasource,
                str(stats)
                )
            for datapoint_id in (x.id for x in datasource.points):
                if datapoint_id in stats:
                    value = stats.get(datapoint_id)
                    dpname = '_'.join((datasource.datasource, datapoint_id))
                    data['values'][datasource.component][dpname] = (value, 'N')

        returnValue(data)
