##############################################################################
#
# Copyright (C) Zenoss, Inc. 2009-2017, all rights reserved.
# Copyright Wes Davis, 2021
#
# The following code is a derivative work of the following Zenoss ZenPacks:
# - ZenPacks.zenoss.Microsoft.Windows 2.9.2
# - ZenPacks.zenoss.LinuxMonitor 2.3.2
#
# which are licensed GPLv2. This code therefore is also licensed under
# the terms of the GNU Public License, version 2.
#
##############################################################################

"""Processes
Interpret the output from the NCPA API and provide performance data for
CPU utilization, total RSS and the number of processes that match the
/Process tree definitions.
"""

import logging
LOG = logging.getLogger('zen.NCPA.processes')

import collections
import json

from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.internet.error import ConnectionLost
from twisted.web.client import getPage
try:
    from twisted.web._newclient import ResponseNeverReceived
except ImportError:
    ResponseNeverReceived = str

from Products.ZenEvents import Event
from Products.ZenEvents.ZenEventClasses import Status_OSProcess
from Products.ZenModel.OSProcessMatcher import OSProcessDataMatcher
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import (
    PythonDataSourcePlugin
    )

from ZenPacks.daviswr.NCPA.lib import ncpaUtil

COUNT_DATAPOINT = 'count'


def _extractProcessMetrics(proc):
    """
    Process the process entry and return back the standard info.

    @parameter proc: process dictionary from api/processes
    @type proc: dict
    @return: pid, rss, cpu, cmdAndArgs (ie full process name)
    @rtype: tuple
    """
    try:
        pid = proc['pid']
        rss = ncpaUtil.get_unit_value(proc['mem_rss'][0], proc['mem_rss'][1])
        cpu = proc['cpu_percent'][0]
        cmdAndArgs = proc['cmd']
        if not cmdAndArgs:
            cmdAndArgs = proc['exe']
        if 'Unknown' == cmdAndArgs or not cmdAndArgs:
            cmdAndArgs = proc['name']

        # ----------------------------------------------------------
        # WARNING! Do not modify this debug line at all!
        # The process class interactive testing UI depends on it!
        # (yeah, yeah... technical debt... we know)
        # ----------------------------------------------------------
        LOG.debug("line '%s' -> pid=%s rss=%s cpu=%s cmdAndArgs=%s",
                  str(proc), pid, rss, cpu, cmdAndArgs)
        # ----------------------------------------------------------

        # NCPA returns current CPU percent rathe than time
        # so it can be graphed and mapped to cpu_pct directly
        return int(pid), int(rss), float(cpu), cmdAndArgs
    except:
        LOG.warn("Unable to parse entry '%s'", str(proc))


def process_metrics(processes):
    """
    Extracts desired metrics from process list returned by the NCPA API

    @parameter processes: contents of api/processes
    @type processes: list
    @return: desired process metrics
    @rtype: list
    """
    metrics = list()
    for proc in processes:
        pid, rss, cpu, processText = _extractProcessMetrics(proc)
        metrics.append({
            'pid': pid,
            'mem': rss,
            'cpu': cpu,
            'processText': processText,
        })

    return metrics


def send_to_debug(error):
    """ From ZenPacks.zenoss.Microsoft.Windows.__init__ """
    try:
        reason = error.value.reasons[0].value
    except Exception:
        reason = ''
    # if ConnectionLost or ResponseNeverReceived, more than
    # likely zenpython stopping.  throw messages to debug
    try:
        if isinstance(reason, ConnectionLost) or\
           isinstance(error.value, ResponseNeverReceived):
            return True
    except AttributeError:
        pass
    return False


class Processes(PythonDataSourcePlugin):
    """ NCPA processes data source plugin """

    @classmethod
    def config_key(cls, datasource, context):
        """ Return a tuple defining collection uniqueness. """
        return(
            context.device().id,
            datasource.getCycleTime(context),
            'processes',
            )

    @classmethod
    def params(cls, datasource, context):
        """ Return params dictionary needed for this plugin. """
        process_class = context.osProcessClass()

        param_attributes = (
            (process_class, 'regex', 'regex'),
            (process_class, 'includeRegex', 'includeRegex'),
            (process_class, 'excludeRegex', 'excludeRegex'),
            (process_class, 'ignoreParameters', 'ignoreParameters'),
            (process_class, 'replaceRegex', 'replaceRegex'),
            (process_class, 'replacement', 'replacement'),
            (process_class, 'primaryUrlPath', 'processClassPrimaryUrlPath'),
            (process_class, 'sequence', 'sequence'),
            (context, 'alertOnRestart', 'alertOnRestart'),
            (context, 'severity', 'getFailSeverity'),
            (context, 'generatedId', 'generatedId'),
            )

        params = {
            'token': context.zNcpaToken,
            'port': context.zNcpaPort,
            }

        # Only set valid params. Different versions of Zenoss have
        # different available attributes for process classes and
        # processes.
        for obj, key, attribute in param_attributes:
            if hasattr(obj, attribute):
                value = getattr(obj, attribute)
                params[key] = value() if callable(value) else value

        return params

    @inlineCallbacks
    def collect(self, config):
        ip_addr = config.manageIp or config.id
        # zProperties aren't going to change between datasources
        token = config.datasources[0].params.get('token', '')
        port = int(config.datasources[0].params.get('port', 5693))

        # Need to raise exceptions for these
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
            endpoint='processes',
            params={'aggregate': 'avg'}
            )

        response = yield getPage(url, method='GET')
        output = json.loads(response)
        LOG.debug('%s: NCPA API output:\n%s', config.id, str(output))

        if 'error' in output:
            # Need to raise an exception here
            LOG.error(
                '%s: %s',
                config.id,
                output.get('error', dict()).get('message', output.get(
                    'error',
                    'An NPCA error occured - check token'
                    ))
                )
            output = dict()
        else:
            output = output.get('root', output).get('processes', output)

        returnValue(output)

    def onSuccess(self, results, config):
        data = self.new_data()
        processes = process_metrics(results)

        if not processes:
            LOG.error('%s: No processes returned by NCPA', config.id)
            return data

        # Using ZenPacks.zenoss.Microsoft.Windows.datasources.ProcessDataSource
        # as an example for OS process handling
        datasource_by_pid = dict()
        metrics_by_component = collections.defaultdict(
            lambda: collections.defaultdict(list)
            )

        # Used for process restart checking.
        if not hasattr(self, 'previous_pids_by_component'):
            self.previous_pids_by_component = collections.defaultdict(set)

        pids_by_component = collections.defaultdict(set)

        sorted_datasource = sorted(
            config.datasources,
            key=lambda x: x.params.get('sequence', 0)
            )

        for proc in processes:
            processText = proc.get(
                'processText',
                'THIS_WILL_NEVER_MATCH_ANYTHING'
                )
            pid = proc.get('pid', -1)

            if -1 == pid:
                continue

            for datasource in sorted_datasource:
                # Assume we're on at least 4.2.5 due to ZPL
                matcher = OSProcessDataMatcher(
                    includeRegex=datasource.params['includeRegex'],
                    excludeRegex=datasource.params['excludeRegex'],
                    replaceRegex=datasource.params['replaceRegex'],
                    replacement=datasource.params['replacement'],
                    primaryUrlPath=datasource.params['primaryUrlPath'],
                    generatedId=datasource.params['generatedId']
                    )

                if not matcher.matches(processText):
                    continue

                datasource_by_pid[pid] = datasource
                pids_by_component[datasource.component].add(pid)

                # Track process count. Append 1 each time we find a
                # match because the generic aggregator below will sum
                # them up to the total count.
                metrics_by_component[datasource.component][COUNT_DATAPOINT].append(1)  # noqa

                # Don't continue matching once a match is found.
                break

        # Send process status events.
        for datasource in config.datasources:
            component = datasource.component

            if COUNT_DATAPOINT in metrics_by_component[component]:
                severity = 0
                summary = 'matching processes running'

                # Process restart checking.
                previous_pids = self.previous_pids_by_component.get(component)
                current_pids = pids_by_component.get(component)

                # No restart if there are no current or previous PIDs.
                # previous PIDs.
                if previous_pids and current_pids:

                    # Only consider PID changes a restart if all PIDs
                    # matching the process changed.
                    if current_pids.isdisjoint(previous_pids):
                        summary = 'matching processes restarted'

                        # If the process is configured to alert on
                        # restart, the first "up" won't be a clear.
                        if datasource.params['alertOnRestart']:
                            severity = datasource.params['severity']

            else:
                severity = datasource.params['severity']
                summary = 'no matching processes running'

                # Add a 0 count for process that aren't running.
                metrics_by_component[component][COUNT_DATAPOINT].append(0)

            data['events'].append({
                'device': datasource.device,
                'component': component,
                'eventClass': datasource.eventClass,
                'eventGroup': 'Process',
                'summary': summary,
                'severity': severity,
            })

        # Prepare for next cycle's restart check by merging current
        # process PIDs with previous. This is to catch restarts that
        # stretch across more than subsequent cycles.
        self.previous_pids_by_component.update(
            (c, p) for c, p in pids_by_component.iteritems() if p)

        for proc in processes:
            pid = proc.get('pid', -1)

            if pid not in datasource_by_pid:
                continue
            datasource = datasource_by_pid[pid]
            for point in datasource.points:
                if point.id == COUNT_DATAPOINT:
                    continue

                LOG.debug(
                    '%s %s: Matching process %s',
                    datasource.device,
                    datasource.component,
                    str(proc)
                    )
                if point.id in proc:
                    value = proc.get(point.id)
                    metrics_by_component[datasource.component][point.id].append(value)  # noqa
                else:
                    LOG.warn(
                        '%s %s: %s not in result',
                        datasource.device,
                        datasource.component,
                        point.id
                        )

        # Aggregate and store datapoint values.
        for component, points in metrics_by_component.iteritems():
            for point, values in points.iteritems():
                value = sum(values)
                data['values'][component][point] = (value, 'N')

        # Send overall clear.
        data['events'].append({
            'device': config.id,
            'severity': Event.Clear,
            'eventKey': 'ProcessScanStatus',
            'eventClass': Status_OSProcess,
            'summary': 'process scan successful',
        })

        return data

    def onError(self, error, config):
        logg = LOG.error
        if send_to_debug(error):
            logg = LOG.debug
        msg = "{} process scan error: {}".format(config.id, error.value)
        logg(msg)

        data = self.new_data()
        data['events'].append({
            'device': config.id,
            'severity': Event.Error,
            'eventKey': 'ProcessScanStatus',
            'eventClass': Status_OSProcess,
            'summary': 'process scan error: {}'.format(error.value),
            })

        return data
