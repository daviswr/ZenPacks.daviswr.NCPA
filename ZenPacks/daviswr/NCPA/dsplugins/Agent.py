""" Monitors device metrics via NCPA """

import logging
LOG = logging.getLogger('zen.NCPA')

import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from Products.ZenUtils.Utils import prepId
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import (
    PythonDataSourcePlugin
    )

from ZenPacks.daviswr.NCPA.lib import ncpaUtil


class Agent(PythonDataSourcePlugin):
    """ NCPA storage device data source plugin """

    @classmethod
    def config_key(cls, datasource, context):
        """ Return a tuple defining collection uniqueness. """
        return(
            context.device().id,
            datasource.getCycleTime(context),
            'agent',
            )

    @classmethod
    def params(cls, datasource, context):
        """ Return params dictionary needed for this plugin. """
        return {
            'token': context.zNcpaToken,
            'port': context.zNcpaPort,
            'bs': context.zNcpaFsBlockSize,
            }

    @inlineCallbacks
    def collect(self, config):
        data = self.new_data()
        ip_addr = config.manageIp or config.id
        # zProperties aren't going to change between datasources
        token = config.datasources[0].params.get('token', '')
        port = int(config.datasources[0].params.get('port', 5693))
        block = int(config.datasources[0].params.get('bs', 4096))

        if not ip_addr:
            LOG.error('%s: No IP address or hostname', config.id)
            returnValue(None)
        elif not token:
            LOG.error('%s: zNcpaToken not set', config.id)
            returnValue(None)

        LOG.debug('%s: Collecting from NCPA client %s', config.id, ip_addr)

        root_url = ncpaUtil.build_url(host=ip_addr, port=port, token=token)

        cpu_avg_url = ncpaUtil.build_url(
            host=ip_addr,
            port=port,
            token=token,
            endpoint='cpu',
            params={'aggregate': 'avg'}
            )

        # CPU percentage endpoint is returned as empty list by parent endpoints
        cpu_pct_url = ncpaUtil.build_url(
            host=ip_addr,
            port=port,
            token=token,
            endpoint='cpu/percent',
            )

        cpu_avg_pct_url = ncpaUtil.build_url(
            host=ip_addr,
            port=port,
            token=token,
            endpoint='cpu/percent',
            params={'aggregate': 'avg'}
            )

        # Processes endpoint is returned as empty list by root endpoint
        proc_url = ncpaUtil.build_url(
            host=ip_addr,
            port=port,
            token=token,
            endpoint='processes',
            params={'aggregate': 'avg'}
            )

        # Services endpoint is returned as empty list by root endpoint
        srv_url = ncpaUtil.build_url(
            host=ip_addr,
            port=port,
            token=token,
            endpoint='services',
            )

        try:
            response = yield getPage(root_url, method='GET')
            output = json.loads(response)
            # Move everything out from under the 'root' key
            output = output.get('root', output)

            response = yield getPage(cpu_avg_url, method='GET')
            # Should give us avg/cpu
            output['avg'] = json.loads(response)

            response = yield getPage(cpu_pct_url, method='GET')
            if 'cpu' not in output:
                output['cpu'] = dict()
            output['cpu'].update(json.loads(response))

            response = yield getPage(cpu_avg_pct_url, method='GET')
            if 'cpu' not in output['avg']:
                output['avg']['cpu'] = dict()
            output['avg']['cpu'].update(json.loads(response))

            response = yield getPage(proc_url, method='GET')
            output.update(json.loads(response))

            response = yield getPage(srv_url, method='GET')
            output.update(json.loads(response))

        except Exception, err:
            LOG.error('%s: %s', config.id, err)
            returnValue(None)

        LOG.debug('%s: NCPA API output:\n%s', config.id, str(output))

        # Parse through API output and gather useful metrics
        stats = {
            'cpu': dict(),
            'disk': dict(),
            'diskstats': dict(),
            'intf': dict(),
            'ncpa': {None: dict()},
            'processes': dict(),
            'services': dict(),
            'sysUpTime': {None: dict()},
            }

        for node_name in output:
            node = output[node_name]
            src = 'ncpa'
            comp = None

            # api/cpu & api/cpu/percent, aggregate=avg
            if 'avg' == node_name:
                LOG.debug('%s: Processing avg api/cpu', config.id)
                subnode = node['cpu']
                stats[src][comp].update({
                    'cpu_idle': int(subnode['idle'][0][0]),
                    'cpu_percent': float(subnode['percent'][0][0]),
                    'cpu_system': int(subnode['system'][0][0]),
                    'cpu_user': int(subnode['user'][0][0]),
                    })
            # api/cpu - CPU components
            elif 'cpu' == node_name:
                LOG.debug('%s: Processing api/cpu', config.id)
                src = 'cpu'
                for item_idx in range(0, len(node['idle'][0])):
                    comp = prepId(str(item_idx))
                    stats[src][comp] = {
                        'idle': int(node['idle'][0][item_idx]),
                        'percent': float(node['percent'][0][item_idx]),
                        'system': int(node['system'][0][item_idx]),
                        'user': int(node['user'][0][item_idx]),
                        }
            # api/disk
            elif 'disk' == node_name:
                src = node_name
                for subnode_name in node:
                    subnode = node[subnode_name]
                    # api/disk/logical - FileSystem components
                    if 'logical' == subnode_name:
                        LOG.debug(
                            '%s: Processing api/disk/logical',
                            config.id
                            )
                        for item_name in subnode:
                            comp = prepId(item_name)
                            item = subnode[item_name]
                            free = ncpaUtil.get_unit_value(
                                item['free'][0],
                                item['free'][1]
                                )
                            used = ncpaUtil.get_unit_value(
                                item['used'][0],
                                item['used'][1]
                                )
                            stats[src][comp] = {
                                'availBlocks': int(free / block),
                                'dskPercent': item['used_percent'][0],
                                'free': free,
                                'used': used,
                                'usedBlocks': int(used / block),
                                }
                            # Windows does not report these metrics
                            if 'inodes' in item:
                                inode_pct = item['inodes_used_percent'][0]
                                stats[src][comp].update({
                                    'availInodes': item['inodes_free'][0],
                                    'usedInodes': item['inodes_used'][0],
                                    'percentInodesUsed': inode_pct,
                                    'totalInodes': item['inodes'][0],
                                    })
                    # api/disk/physical - HardDisk components
                    elif 'physical' == subnode_name:
                        LOG.debug(
                            '%s: Processing api/disk/physical',
                            config.id
                            )
                        src = 'diskstats'
                        for item_name in subnode:
                            comp = prepId(item_name)
                            item = subnode[item_name]
                            stats[src][comp] = {
                                'DiskReadBytesSec': ncpaUtil.get_unit_value(
                                    item['read_bytes'][0],
                                    item['read_bytes'][1]
                                    ),
                                'DiskWriteBytesSec': ncpaUtil.get_unit_value(
                                    item['write_bytes'][0],
                                    item['write_bytes'][1]
                                    ),
                                'msReading': item['read_time'][0],
                                'msWriting': item['write_time'][0],
                                'readsCompleted': item['read_count'][0],
                                'writesCompleted': item['write_count'][0],
                                }
            # api/interface - IPInterface components
            elif 'interface' == node_name:
                LOG.debug('%s: Processing api/interface', config.id)
                # Emulate ZenCommand-based datasource name
                src = 'intf'
                for item_name in node:
                    comp = prepId(item_name)
                    item = node[item_name]
                    stats[src][comp] = {
                        # Emulate ZenCommand-based datapoint names
                        'ifInOctets': ncpaUtil.get_unit_value(
                            item['bytes_recv'][0],
                            item['bytes_recv'][1]
                            ),
                        'ifOutOctets': ncpaUtil.get_unit_value(
                            item['bytes_sent'][0],
                            item['bytes_sent'][1]
                            ),
                        'ifInDiscards': item['dropin'][0],
                        'ifOutDiscards': item['dropout'][0],
                        'ifInErrors': item['errin'][0],
                        'ifOutErrors': item['errout'][0],
                        'ifInPackets': item['packets_recv'][0],
                        'ifOutPackets': item['packets_sent'][0],
                        }
            # api/memory
            elif 'memory' == node_name:
                for subnode_name in node:
                    subnode = node[subnode_name]
                    # It's possible that a machine with swap disabled
                    # may not have api/memory/swap node
                    if 'swap' == subnode_name:
                        LOG.debug(
                            '%s: Processing api/memory/swap',
                            config.id
                            )
                        stats[src][comp].update({
                            'swap_free': ncpaUtil.get_unit_value(
                                subnode['free'][0],
                                subnode['free'][1],
                                ),
                            'swap_percent': float(subnode['percent'][0]),
                            'swap_used': ncpaUtil.get_unit_value(
                                subnode['used'][0],
                                subnode['used'][1],
                                ),
                            })
                        # Windows does not report these metrics
                        if ('swapped_in' in subnode
                                and 'swapped_out' in subnode):
                            stats[src][comp].update({
                                'swap_in': ncpaUtil.get_unit_value(
                                    subnode['swapped_in'][0],
                                    subnode['swapped_in'][1],
                                    ),
                                'swap_out': ncpaUtil.get_unit_value(
                                    subnode['swapped_out'][0],
                                    subnode['swapped_out'][1],
                                    )
                                })
                    elif subnode_name == 'virtual':
                        LOG.debug(
                            '%s: Processing api/memory/virtual',
                            config.id
                            )
                        stats[src][comp].update({
                            'memory_available': ncpaUtil.get_unit_value(
                                subnode['available'][0],
                                subnode['available'][1],
                                ),
                            'memory_free': ncpaUtil.get_unit_value(
                                subnode['free'][0],
                                subnode['free'][1],
                                ),
                            'memory_percent': float(subnode['percent'][0]),
                            'memory_used': ncpaUtil.get_unit_value(
                                subnode['used'][0],
                                subnode['used'][1],
                                ),
                            })
            # api/processes
            elif 'processes' == node_name:
                LOG.debug('%s: Processing api/processes', config.id)
                # Device-level metrics
                stats[src][comp]['mem_rss'] = 0
                stats[src][comp]['mem_vms'] = 0
                stats[src][comp]['proc_cpu'] = 0.0
                stats[src][comp]['proc_mem'] = 0.0
                stats[src][comp]['processes'] = len(node)
                # processes node is a list, rather than a dict
                for item in node:
                    stats[src][comp]['mem_rss'] += ncpaUtil.get_unit_value(
                        item['mem_rss'][0],
                        item['mem_rss'][1],
                        )
                    stats[src][comp]['mem_vms'] += ncpaUtil.get_unit_value(
                        item['mem_vms'][0],
                        item['mem_vms'][1],
                        )
                    mem_pct = item.get('mem_percent', [0.0, ''])[0]
                    stats[src][comp]['proc_mem'] += mem_pct
                    if item.get('name', '') == 'System Idle Process':
                        # CPU will always read 100% if System Idle is included
                        stats[src][comp]['processes'] -= 1
                    else:
                        cpu_pct = item.get('cpu_percent', [0.0, ''])[0]
                        stats[src][comp]['proc_cpu'] += cpu_pct

            # api/services - NcpaService components
            elif 'services' == node_name:
                LOG.debug('%s: Processing api/services', config.id)
                src = node_name
                for item_name in node:
                    comp = prepId(item_name)
                    item = node[item_name]
                    stats[src][comp] = {
                        'status': ncpaUtil.service_states.get(
                            item,
                            ncpaUtil.service_states.get('unknown', 2)
                            )
                        }
            # api/system
            elif 'system' == node_name:
                LOG.debug('%s: Processing api/system', config.id)
                src = 'sysUpTime'
                stats[src][comp]['sysUpTime'] = int(node['uptime'][0] * 100)
            # api/user
            elif 'user' == node_name:
                LOG.debug('%s: Processing api/user', config.id)
                stats[src][comp]['users'] = int(node['count'][0])

        # Report the metrics gathered
        for datasource in config.datasources:
            LOG.debug(
                '%s: Component %s datasource %s',
                config.id,
                datasource.component,
                datasource.datasource
                )
            if datasource.datasource in stats:
                src = datasource.datasource
                comp = None if src in ['ncpa', 'sysUpTime'] \
                    else datasource.component
                for datapoint in datasource.points:
                    if comp in stats[src] and datapoint.id in stats[src][comp]:
                        value = stats[src][comp][datapoint.id]
                        data['values'][comp][datapoint.dpName] = (value, 'N')

        returnValue(data)
