from ZenPacks.daviswr.NCPA.lib.ncpaUtil import service_states

service_strings = dict(map(reversed, service_states.items()))

if evt.eventKey.endswith('|Service Status'):
    status = service_strings.get(int(float(evt.current)), 'unknown')
    evt.summary = '{0} service is {1}'.format(evt.component, status)
