#!/usr/bin/python
# -----------------------------------------------------------------------------
# Simple radio: implementation of class Base
#
# The class Base is the root-class of all classes and implements common methods
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import sys

class Base(object):
  """ base class with common methods """

  # --- print debug messages   ------------------------------------------------

  def debug(self,text):
    """ print debug-message """

    if self._debug:
      sys.stderr.write("[DEBUG] %s\n" % text)
      sys.stderr.flush()

  # --- read configuration value   --------------------------------------------

  def get_value(self,parser,section,option,default):
    """ get value of config-variables and return given default if unset """

    if parser.has_section(section):
      try:
        value = parser.get(section,option)
      except:
        value = default
    else:
      value = default
    return value