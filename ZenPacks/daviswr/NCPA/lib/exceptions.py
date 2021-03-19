""" Nagios Cross-Platform Agent errors """


class NcpaError(Exception):
    """ Generic Nagios Cross-Platform Agent error """
    def __init__(self, value):
        self.value = value
        self.message = self.value
        self.msg = self.value

    def __str__(self):
        return str(self.value)

    def __repr__(self):
        return str(self)


class NcpaIncorrectCredentialsError(NcpaError):
    """ Incorrect credentials given """
    pass


class NcpaNodeDoesNotExistError(NcpaError):
    """ The node requested does not exist """
    def __init__(self, value, node='', path=''):
        self.value = value
        self.message = self.value
        self.msg = self.value
        self.node = node
        self.path = path
