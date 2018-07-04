#!/usr/bin/python
# -----------------------------------------------------------------------------
# Simple radio: implementation of class Amp
#
# The class Amp implements the interface to the amplifier
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import os, subprocess, shlex

from SRBase import Base

class Amp(Base):
  """ Amp-controller """

  def __init__(self,app):
    """ initialization """

    self._app    = app
    self._volume = -1                 # and unknown volume

    self.read_config()
    app.register_funcs(self.get_funcs())

  # --- read configuration   --------------------------------------------------

  def read_config(self):
    """ read configuration from config-file """

    # section [GLOBAL]
    self._debug = self.get_value(self._app.parser,"GLOBAL", "debug","0") == "1"

    # section [AMP]
    self._mixer       = self.get_value(self._app.parser,"AMP","mixer","PCM")
    self._mixer_opts  = self.get_value(self._app.parser,"AMP","mixer_opts","")

  # --- query current volume   ------------------------------------------------

  def _get_volume(self):
    """ query current volume """

    if self._volume != -1:
      return self._volume

    try:
      cmd = ( "amixer %s get %s|grep -o [0-9]*%%|sed 's/%%//'| head -n 1" %
              (self._mixer_opts,self._mixer) )
      self._volume = int(subprocess.check_output(cmd,shell=True).splitlines()[0])
      self.debug("current volume is: %d%%" % self._volume)
      return self._volume
    except:
      if self._debug:
        print traceback.format_exc()
      return -1

  # --- set volume   ----------------------------------------------------------

  def _set_volume(self,volume):
    """ set volume """

    self.debug("setting volume to %d%%" % volume)
    try:
      args = shlex.split("amixer %s -q set %s %d%%" %
                                       (self._mixer_opts,self._mixer,volume))
      subprocess.call(args)
      self._volume = volume
    except:
      if self._debug:
        print traceback.format_exc()

  # --- turn volume up   ------------------------------------------------------

  def func_volume_up(self,_):
    """ turn volume up """

    self.debug("turn volume up")
    current_volume = self._get_volume()
    self._set_volume(min(current_volume+1,100))

  # --- turn volume down   ----------------------------------------------------

  def func_volume_down(self,_):
    """ turn volume down """

    self.debug("turn volume down")
    current_volume = self._get_volume()
    self._set_volume(max(current_volume-1,0))

  # --- toggle mute   ---------------------------------------------------------

  def func_toggle_mute(self,_):
    """ toggle mute """

    self.debug("toggle mute")
    subprocess.call(["amixer","-q","sset",self._mixer,"toggle"])

