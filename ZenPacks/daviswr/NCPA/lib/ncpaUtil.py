""" A library of NCPA-related functions """

from urllib import urlencode

multipliers = {
    'B': 1,
    'KiB': 1024,
    'MiB': 1024**2,
    'GiB': 1024**3,
    'TiB': 1024**4,
    'PiB': 1024**5,
    'KB': 1000,
    'MB': 1000**2,
    'GB': 1000**3,
    'TB': 1000**4,
    'PB': 1000**5,
    }


def build_url(host, port, token, endpoint='', params=None):
    """ Returns an NCPA API endpoint URL """
    api_params = {'token': token, 'units': 'B'}
    api_params.update(params if params else {})

    # Unsure if this check is necessary
    if ((isinstance(port, str) and not port.isdigit())
            or not isinstance(port, int)):
        port = 5693

    return 'https://{0}:{1}/api/{2}?{3}'.format(
        host,
        port,
        endpoint if endpoint else '',
        urlencode(api_params)
        )


def get_unit_value(value, unit):
    """ Returns value multiplied by given unit """
    return int(float(value) * multipliers.get(unit, 1))
