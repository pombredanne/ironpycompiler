#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Defines the data types used in IronPyCompiler.

"""

import distutils.version
import platform


class PythonVersion(distutils.version.StrictVersion):

    """Represents a Python version.

    :param str vstring: String showing a Python version, like '2.7.8'. If this
                        parameter is not provided, the return value of
                        :func:`platform.python_version` will be used.

    .. versionadded:: 1.0.0
    """

    def __init__(self, vstring=None):
        """Initalize the instance.

        """

        if vstring is None:
            vstring = platform.python_version()
        distutils.version.StrictVersion.__init__(self, vstring)

        #: Integer showing the major version.
        self.major = self.version[0]

        #: Integer showing the minor version.
        self.minor = self.version[1]

        #: Integer showing the patch version.
        self.patch = self.version[2]
