""" A library of NCPA-related functions """

from urllib import urlencode

from ZenPacks.daviswr.NCPA.lib.exceptions import (
    NcpaError,
    NcpaIncorrectCredentialsError,
    NcpaNodeDoesNotExistError
    )

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

service_states = {
    'running': 0,
    'stopped': 1,
    'paused': 2,
    'start_pending': 3,
    'stop_pending': 4,
    'pause_pending': 5,
    'continue_pending': 6,
    'unknown': 10,
    }


def build_url(host, port, token, endpoint=None, params=None):
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


def error_check(output, device=None, log=None):
    """ Checks for error message in NCPA API output and raise an exception """
    if 'error' in output:
        error = output['error']
        err_str = (error.get('message', 'An unknown NCPA error occurred')
                   if isinstance(error, dict) else str(error))
        if device and log:
            log.error('%s: %s', device, err_str)

        if 'incorrect credentials' in err_str.lower():
            raise NcpaIncorrectCredentialsError(err_str)
        elif 'node requested does not exist' in err_str.lower():
            if isinstance(error, dict):
                raise NcpaNodeDoesNotExistError(
                    value=err_str,
                    node=error['node'],
                    path=error['path']
                    )
            else:
                raise NcpaNodeDoesNotExistError(err_str)
        else:
            raise NcpaError(err_str)


def get_unit_value(value, unit):
    """ Returns value multiplied by given unit """
    return int(float(value) * multipliers.get(unit, 1))
