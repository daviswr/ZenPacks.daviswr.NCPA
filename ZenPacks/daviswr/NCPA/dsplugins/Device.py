""" Monitors system-level NCPA metrics """

import logging
LOG = logging.getLogger('zen.NCPA')

import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import (
    PythonDataSourcePlugin
    )

from ZenPacks.daviswr.NCPA.lib import ncpaUtil


class Device(PythonDataSourcePlugin):
    """ NCPA system-level data source plugin """

    @classmethod
    def config_key(cls, datasource, context):
        """ Return a tuple defining collection uniqueness. """
        return(
            context.device().id,
            datasource.getCycleTime(context),
            context.id,
            'ncpa',
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

        for datasource in config.datasources:
            urls = list()
            if 'sysUpTime' == datasource.datasource:
                urls.append(ncpaUtil.build_url(
                    host=ip_addr,
                    port=port,
                    token=token,
                    endpoint='system/uptime'
                    ))
            else:
                urls.append(ncpaUtil.build_url(
                    host=ip_addr,
                    port=port,
                    token=token,
                    endpoint='cpu/percent',
                    params={'aggregate': 'avg'}
                    ))

                urls.append(ncpaUtil.build_url(
                    host=ip_addr,
                    port=port,
                    token=token,
                    endpoint='memory'
                    ))

                urls.append(ncpaUtil.build_url(
                    host=ip_addr,
                    port=port,
                    token=token,
                    endpoint='processes',
                    params={'aggregate': 'avg'}
                    ))

                urls.append(ncpaUtil.build_url(
                    host=ip_addr,
                    port=port,
                    token=token,
                    endpoint='user/count'
                    ))

            output = dict()
            try:
                for url in urls:
                    response = yield getPage(url, method='GET')
                    output.update(json.loads(response))

            except Exception, err:
                LOG.error('%s: %s', config.id, err)
                returnValue(None)

            LOG.debug(
                '%s: %s NCPA API output:\n%s',
                config.id,
                datasource.datasource,
                str(output)
                )
            stats = dict()
            # api/system/uptime
            if output.get('uptime', list()):
                # Convert seconds to timeticks
                stats['sysUpTime'] = int(output['uptime'][0] * 100)

            # api/cpu/percent
            if output.get('percent', list()):
                stats['cpu_percent'] = float(output['percent'][0][0])

            # api/memory
            if output.get('memory', dict()).get('virtual', dict()):
                memory = output['memory']['virtual']
                stats['memory_available'] = ncpaUtil.get_unit_value(
                    memory['available'][0],
                    memory['available'][1],
                    )
                stats['memory_free'] = ncpaUtil.get_unit_value(
                    memory['free'][0],
                    memory['free'][1],
                    )
                stats['memory_used'] = ncpaUtil.get_unit_value(
                    memory['used'][0],
                    memory['used'][1],
                    )
                stats['memory_percent'] = float(memory['percent'][0])

            if output.get('memory', dict()).get('swap', dict()):
                swap = output['memory']['swap']
                stats['swap_free'] = ncpaUtil.get_unit_value(
                    swap['free'][0],
                    swap['free'][1],
                    )
                stats['swap_used'] = ncpaUtil.get_unit_value(
                    swap['used'][0],
                    swap['used'][1],
                    )
                stats['swap_percent'] = float(swap['percent'][0])
                # Windows does not report these metrics
                if 'swapped_out' in swap:
                    stats['swap_out'] = ncpaUtil.get_unit_value(
                        swap['swapped_out'][0],
                        swap['swapped_out'][1],
                        )
                if 'swapped_in' in swap:
                    stats['swap_in'] = ncpaUtil.get_unit_value(
                        swap['swapped_in'][0],
                        swap['swapped_in'][1],
                        )

            # api/processes
            if output.get('processes', list()):
                stats['processes'] = len(output['processes'])
                stats['mem_rss'] = 0
                stats['mem_vms'] = 0
                stats['proc_cpu'] = 0.0
                stats['proc_mem'] = 0.0
                for process in output['processes']:
                    stats['mem_rss'] += ncpaUtil.get_unit_value(
                        process['mem_rss'][0],
                        process['mem_rss'][1],
                        )
                    stats['mem_vms'] += ncpaUtil.get_unit_value(
                        process['mem_vms'][0],
                        process['mem_vms'][1],
                        )
                    mem_pct = process.get('mem_percent', [0.0, ''])[0]
                    stats['proc_mem'] += mem_pct
                    if process.get('name', '') == 'System Idle Process':
                        # CPU will always read 100% if System Idle is included
                        stats['processes'] -= 1
                    else:
                        cpu_pct = process.get('cpu_percent', [0.0, ''])[0]
                        stats['proc_cpu'] += cpu_pct

            # api/user/count
            if output.get('count', list()):
                stats['users'] = output['count'][0]

            LOG.debug(
                '%s: %s NCPA metrics:\n%s',
                config.id,
                datasource.datasource,
                str(stats)
                )
            for datapoint in datasource.points:
                if datapoint.id in stats:
                    value = stats.get(datapoint.id)
                    data['values'][None][datapoint.dpName] = (value, 'N')

        returnValue(data)
