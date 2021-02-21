#!/usr/bin/python3
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Simple radio: implementation of class Lirc
#
# The class Keypad translates LIRC-commands to functions
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import select, os, socket, traceback
from threading import Thread

from SRBase import Base

POLL_TIME = 2
LIRC_SOCKET = "/var/run/lirc/lircd"

class Lirc(Thread,Base):
  """ LIRC-controller """

  def __init__(self,app):
    """ initialization """
    super(Lirc,self).__init__(name="Lirc")
    self._app     = app
    self._keymap  = {}
    self.read_config()

  # --- read configuration   --------------------------------------------------

  def read_config(self):
    """ read configuration from config-file """

    # section [GLOBAL]
    self._debug  = self.get_value(self._app.parser,"GLOBAL", "debug","0") == "1"
    self._active = self.get_value(self._app.parser,"GLOBAL", "lirc","0") == "1"
    if not self._active:
      return

    # section [LIRC]
    for (key,func) in self._app.parser.items("LIRC"):
      words = func.split()
      words.extend([0,0])
      [func_name,func_repeat,func_delay] = words[:3]
      self._keymap[key] = (func_name,func_repeat,func_delay)

  # --- poll keys   ---------------------------------------------------------

  def run(self):
    """ poll keys from pipe """

    self.debug("starting Lirc.run()")
    if not self._active:
      self.debug("LIRC not active: terminating Lirc.run()")
      return

    # wait for socket
    socket_wait = 0.5
    while not os.path.exists(LIRC_SOCKET):
      self.debug("waiting for socket ...")
      if socket_wait < POLL_TIME/2:
        socket_wait *= 2
      if self._app.stop_event.wait(socket_wait):
        # program ended, before we actually started
        return

    # make sure the open call does not block
    lirc_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    lirc_socket.connect(LIRC_SOCKET)
    p_fd = lirc_socket.fileno()
    lirc_file = lirc_socket.makefile('r')
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
          key = lirc_file.readline().rstrip('\n')
          self.debug("key read: %s" % key)
          if key:
            self.process_key(key)
        except:
          if self._debug:
            traceback.print_exc()

    # cleanup work after termination
    self.debug("terminating Lirc.run() on stop request")
    poll_obj.unregister(lirc_socket)
    lirc_file.close()
    lirc_socket.close()

  # --- process key   ---------------------------------------------------------

  def process_key(self,key):
    """ map key to command and execute it"""

    self.debug("processing key %s" % key)

    [_hex,rep_count,key_name,_irname] = key.split(" ")
    rep_count = int(rep_count)

    # check for valid KEY (should not happen)
    if not self._keymap.has_key(key_name):
      self.debug("unsupported key %s" % key_name)
      return

    (func_name,func_repeat,func_delay) = self._keymap[key_name]
    func_repeat = int(func_repeat)
    func_delay  = int(func_delay)

    # check repeat and delay count (only relevant for positive rep_count)
    if rep_count > 0:
      if func_delay > 0 and func_delay <= rep_count:
        return
      # check repeat
      if func_repeat == 0:
        #ignore key repeat
        return
      else:
        # ignore all but every nth repeat
        if rep_count % func_repeat > 0:
          return

    # delegate execution to class App (we strip the prefix 'KEY_')
    self._app.exec_func(func_name,key_name.lstrip("KEY_"))
