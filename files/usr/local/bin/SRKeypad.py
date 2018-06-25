#!/usr/bin/python
# -----------------------------------------------------------------------------
# Simple radio: implementation of class Keypad
#
# The class Keypad controls a 16-key capacitative keypad
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import threading, os, select, traceback
from threading import Thread

from SRBase import Base

FIFO_NAME = "/var/run/ttp229-keypad.fifo"
POLL_TIME = 2

class Keypad(Thread,Base):
  """ Keypad-controller """

  KEYPAD_RADIO  = 0
  KEYPAD_PLAYER = 1

  def __init__(self,app):
    """ initialization """
    super(Keypad,self).__init__(name="Keypad")
    self._app     = app
    self._keymaps = []

  # --- read configuration   --------------------------------------------------

  def read_config(self):
    """ read configuration from config-file """

    # section [GLOBAL]
    self._debug  = self.get_value(self._app.parser,"GLOBAL", "debug","0") == "1"

    # section [KEYS]
    key_map = {}
    for (key,func_name) in self._app.parser.items("KEYS"):
      key_map[key] = func_name
    self._keymaps.append(key_map)

    # section [PLAYER]
    key_map = {}
    for (key,func_name) in self._app.parser.items("PLAYER"):
      key_map[key] = func_name
    self._keymaps.append(key_map)

    # the default key-map is the radio-keymap
    self._map_index = Keypad.KEYPAD_RADIO

  # --- set the keymap to use   ---------------------------------------------

  def set_keymap(self,map):
    """ set the keymap to use """
    self._map_index = map

  # --- poll keys   ---------------------------------------------------------

  def run(self):
    """ poll keys from pipe """

    self.debug("starting poll_keys")

    # wait for pipe
    pipe_wait = 0.5
    while not os.path.exists(FIFO_NAME):
      self.debug("waiting for pipe ...")
      if pipe_wait < POLL_TIME/2:
        pipe_wait *= 2
      if self._app.stop_event.wait(pipe_wait):
        # program ended, before we actually started
        return

    # make sure the open call does not block
    p_fd = os.open(FIFO_NAME,os.O_RDONLY|os.O_NONBLOCK)
    pipe = os.fdopen(p_fd,"r")
    poll_obj = select.poll()
    poll_obj.register(p_fd,select.POLLPRI|select.POLLIN)

    # main loop
    while True:
      if self._app.stop_event.wait(0.01):
        break
      poll_result = poll_obj.poll(POLL_TIME*1000)
      for (fd,event) in poll_result:
        # do some sanity checks
        if event & select.POLLHUP == select.POLLHUP:
          # we just wait, continue and hope the key-provider comes back
          if self._app.stop_event.wait(POLL_TIME):
            break
          continue

        try:
          key = pipe.readline().rstrip('\n')
          self.debug("key read: %s" % key)
          if key:
            self.process_key(key)
        except:
          if self._debug:
            print traceback.format_exc()

    # cleanup work after termination
    self.debug("terminating poll_keys on stop request")
    poll_obj.unregister(pipe)
    pipe.close()               # also closes the fd

  # --- process key   ---------------------------------------------------------

  def process_key(self,key):
    """ map key to command and execute it"""

    self.debug("processing key %s" % key)
    if not self._keymaps[self._map_index].has_key(key):
      self.debug("unsupported key %s" % key)
      return
    # delegate execution to class App
    self._app.exec_func(self._keymaps[self._map_index][key],key)

