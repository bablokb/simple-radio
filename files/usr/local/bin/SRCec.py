#!/usr/bin/python
# -----------------------------------------------------------------------------
# Simple radio: implementation of class CECController
#
# The class CECController is the interface to the CEC-system
#
# Part of this code is copied from the libcec-source taken from
# libcec/src/pyCecClient/pyCecClient.py
#
#libCEC(R) is Copyright (C) 2011-2015 Pulse-Eight Limited.  All rights reserved.
#libCEC(R) is a original work, containing original code.
#libCEC(R) is a trademark of Pulse-Eight Limited.
# License: GPL2 (original libcec-license)
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import os

try:
  import cec
  have_cec_import = True
except ImportError:
  print("[WARNING] could not import cec")
  have_cec_import = False

from SRBase import Base

class CECController(Base):
  """ CECController-controller """

  def __init__(self,app):
    """ initialization """

    self._app = app
    self.read_config()
    if self._have_cec:
      self._init_cec()

  # --- read configuration   --------------------------------------------------

  def read_config(self):
    """ read configuration from config-file """

    # section [GLOBAL]
    self._debug  = self.get_value(self._app.parser,"GLOBAL", "debug","0") == "1"
    want_cec     = self.get_value(self._app.parser, "GLOBAL", "cec","0")  == "1"
    self._have_cec = have_cec_import and want_cec

  # --- initialize CEC   ------------------------------------------------------

  def _init_cec(self):
    """ initialize CEC if available """

    self._log_level = cec.CEC_LOG_WARNING
    self._cecconfig = cec.libcec_configuration()
    self._cecconfig.strDeviceName   = "simple-radio"
    self._cecconfig.bActivateSource = 0
    self._cecconfig.deviceTypes.Add(cec.CEC_DEVICE_TYPE_TUNER)
    self._cecconfig.clientVersion = cec.LIBCEC_VERSION_CURRENT

    self._cecconfig.SetLogCallback(self._process_logmessage)
    self._cecconfig.SetKeyPressCallback(self._process_key)
    self._cecconfig.SetCommandCallback(self._process_command)

    self._controller = cec.ICECAdapter.Create(self._cecconfig)
    self.debug("libCEC version " +
          self._controller.VersionToString(self._cecconfig.serverVersion) +
          " loaded: " + self._controller.GetLibInfo())

    # search for adapters
    self._com_port = self.get_com_port()

    if self._com_port == None:
      self._have_cec = False
      return
    
    if not self._controller.Open(self._com_port):
      self.debug("could not open cec-adapter")
      self._have_cec = False

  # --- process key presses   ------------------------------------------------
  
  def _process_key(self, key, duration):
    """ process keys """

    # if the remote sends keys, we could map the keys to commands here
    self.debug("key: " + str(key))
    return 0

  # --- process commands   ---------------------------------------------------
  
  def _process_command(self, cmd):
    """ process commands """

    # if the remote sends (correct) commands, we could take actions here
    # e.g. turn on the radio
    self.debug("cec command: " + cmd)
    return 0

  # --- process log-messages   ------------------------------------------------
  
  def _process_logmessage(self, level, time, message):
    """ process log messages (just send them to debug-output) """
    if level > self._log_level:
      return 0

    if level == cec.CEC_LOG_ERROR:
      levelstr = "CEC-ERROR:   "
    elif level == cec.CEC_LOG_WARNING:
      levelstr = "CEC-WARNING: "
    elif level == cec.CEC_LOG_NOTICE:
      levelstr = "CEC-NOTICE:  "
    elif level == cec.CEC_LOG_TRAFFIC:
      levelstr = "CEC-TRAFFIC: "
    elif level == cec.CEC_LOG_DEBUG:
      levelstr = "CEC-DEBUG:   "

    self.debug(levelstr + "[" + str(time) + "]     " + message)
    return 0

  # --- return com port path of adapter   -------------------------------------

  def _get_com_port(self):
    """ query (first) available adapter """

    for adapter in self._controller.DetectAdapters():
      self.debug("CEC Adapter:")
      self.debug("Port:     " + adapter.strComName)
      self.debug("vendor:   " + hex(adapter.iVendorId))
      self.debug("Produkt:  " + hex(adapter.iProductId))
      return adapter.strComName

    self.debug("no cec adapter found")
    return None

  # --- return cec-availability   ---------------------------------------------

  def have_cec(self):
    """ return cec-availability """

    return self._have_cec

  # --- increase volume -------------------------------------------------------

  def volume_up(self):
    """ increase volume (delegate to receiver) """

    if self._have_cec:
      self._controller.VolumeUp()

  # --- decrease volume   ----------------------------------------------------

  def volume_down(self):
    """ decrease volume (delegate to receiver) """

    if self._have_cec:
      self._controller.VolumeDown()

  # --- send mute command   --------------------------------------------------
  
  def toggle_mute(self):
    """ toggle mute (delegate to receiver) """

    if self._have_cec:
      self._controller.AudioToggleMute()
