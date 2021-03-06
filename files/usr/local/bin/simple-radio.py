#!/usr/bin/python3
# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Simple radio implementation
#   - read channels from file
#   - read keys from pipe and switch channels accordingly
#   - display ICY-META-tags on display
#   - record radio (inspired by https://github.com/radiorec)
#     Copyright (C) 2013  Martin Brodbeck <martin@brodbeck-online.de>
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import locale, os, sys, json, traceback
from   argparse import ArgumentParser
import threading, signal
import configparser

from SRBase     import Base

# --- helper class for options   --------------------------------------------

class Options(object):
  pass

# --- cmdline-parser   ------------------------------------------------------

def get_parser():
  """ configure cmdline-parser """

  parser = ArgumentParser(add_help=False,
    description='Simple radio')

  parser.add_argument('-p', '--play', action='store_true',
    dest='do_play', default=True,
    help="play radio (default)")

  parser.add_argument('-l', '--list', action='store_true',
    dest='do_list', default=False,
    help="display radio-channels")

  parser.add_argument('-r', '--record', action='store_true',
    dest='do_record', default=False,
    help="record radio (needs channel as argument)")
  parser.add_argument('-t', '--tdir', nargs=1,
    metavar='target directory', default=None,
    dest='target_dir',
    help='target directory for recordings')

  parser.add_argument('-h', '--help', action='help',
    help='print this help')

  parser.add_argument('channel', nargs='?', metavar='channel',
    default=None, help='channel number')
  parser.add_argument('duration', nargs='?', metavar='duration',
    default=0, help='duration of recording')
  return parser

# --- validate and fix options   ---------------------------------------------

def check_options(options):
  """ validate and fix options """

  # record needs a channel number
  if options.do_record and not options.channel:
    print("[ERROR] record-option (-r) needs channel nummber as argument")
    sys.exit(3)

# --- main application class   ----------------------------------------------

class App(Base):
  """ main application class """

  def __init__(self,options):
    """ initialization """

    self.options    = options
    self.parser     = configparser.RawConfigParser(inline_comment_prefixes=(';',))
    self.parser.optionxform = str
    self.parser.read('/etc/simple-radio.conf')

    self.read_config()
    self._store = os.path.join(os.path.expanduser("~"),".simple-radio.json")

    self._threads    = []                   # thread-store
    self.stop_event  = threading.Event()
    self._functions  = {}                   # maps user-functions to methods
    self.register_funcs(self.get_funcs())

    # create all objects
    if options.do_record:
      from SRRadio    import Radio
      from SRRecorder import Recorder
      self.radio    = Radio(self)
      self.recorder = Recorder(self)
      self._objects = [self,self.radio,self.recorder]
    elif options.do_list:
      from SRRadio    import Radio
      self.radio    = Radio(self)
      self._objects = [self,self.radio]
    else:
      from SRKeypad   import Keypad
      from SRDisplay  import Display
      from SRRadio    import Radio
      from SRRecorder import Recorder
      from SRPlayer   import Player
      from SRMpg123   import Mpg123
      from SRAmp      import Amp
      from SRLirc     import Lirc
      from SRCec      import CECController
      self.keypad   = Keypad(self)
      self.lirc     = Lirc(self)
      self.radio    = Radio(self)
      self.player   = Player(self)
      self.recorder = Recorder(self)
      self.mpg123   = Mpg123(self)
      self.amp      = Amp(self)
      self.display  = Display(self)
      self.cec      = CECController(self)
      self._objects = [self,self.keypad,self.lirc,self.radio,self.player,
                       self.recorder,self.mpg123,self.amp,self.display,self.cec]
    self._load_state()

  # --- read configuration   --------------------------------------------------

  def read_config(self):
    """ read configuration from config-file """

    # section [GLOBAL]
    self._debug  = self.get_value(self.parser,"GLOBAL", "debug","0") == "1"

  # --- register functions   --------------------------------------------------

  def register_funcs(self,func_map):
    """ register functions im map (called by every class providing functions) """

    self._functions.update(func_map)

  # --- execute function   ----------------------------------------------------

  def exec_func(self,func_name,key):
    """ execute logical function """

    if func_name in self._functions:
      func = self._functions[func_name]
      if func.__self__.is_active():
        self.debug("executing: %s" % func_name)
        func(key)
      else:
        self.debug("ignoring: %s (not active)" % func_name)

  # --- switch to player mode   -----------------------------------------------

  def func_start_playmode(self,_):
    """ start player mode """

    self.debug("starting player mode")
    self.radio.set_state(False)
    self.mpg123.stop()
    self.keypad.set_keymap(self.keypad.KEYPAD_PLAYER)
    self.player.set_state(True)
    self.display.set_content_provider(self.player)

  # --- exit player mode   ----------------------------------------------------

  def func_exit_playmode(self,_):
    """ stop player mode, start radio mode """

    self.debug("stopping player mode")
    self.player.set_state(False)
    self.mpg123.stop()
    self.display.clear()
    self.keypad.set_keymap(self.keypad.KEYPAD_RADIO)
    self.display.set_content_provider(self.radio)
    self.radio.set_state(True)

  # --- shutdown system   -----------------------------------------------------

  def func_shutdown(self,_):
    """ shutdown system """

    self.debug("processing shutdown")
    self.mpg123.stop()
    if not self._debug:
      try:
        os.system("sudo /sbin/halt &")
      except:
        pass
    else:
      self.debug("no shutdown in debug-mode")

  # --- reboot system   -----------------------------------------------------

  def func_reboot(self,_):
    """ reboot system """

    self.debug("processing reboot")
    self.mpg123.stop()
    if not self._debug:
      try:
        os.system("sudo /sbin/reboot &")
      except:
        pass
    else:
      self.debug("no reboot in debug-mode")

  # --- restart system   ------------------------------------------------------

  def func_restart(self,_):
    """ restart system """

    self.debug("processing restart")
    self.mpg123.stop()
    if not self._debug:
      try:
        os.system("sudo /bin/systemctl restart simple-radio.service &")
      except:
        pass
    else:
      self.debug("no restart in debug-mode")

  # --- query state of objects and save   -------------------------------------

  def _save_state(self):
    """ query and save state of objects """

    state = {}
    for obj in self._objects:
      state[obj.__module__] = obj.get_persistent_state()

    f = open(self._store,"w")
    self.debug("Saving settings to %s" % self._store)
    json.dump(state,f,indent=2,sort_keys=True)
    f.close()

  # --- load state of objects   -----------------------------------------------

  def _load_state(self):
    """ load state of objects """

    try:
      if not os.path.exists(self._store):
        return
      self.debug("Loading settings from %s" % self._store)
      f = open(self._store,"r")
      state = json.load(f)
      for obj in self._objects:
        if obj.__module__ in state:
          obj.set_persistent_state(state[obj.__module__])
      f.close()
    except:
      self.debug("Loading settings failed")
      if self._debug:
        traceback.print_exc()

  # --- setup signal handler   ------------------------------------------------

  def signal_handler(self,_signo, _stack_frame):
    """ signal-handler for clean shutdown """

    self.debug("received signal, stopping program ...")
    if hasattr(self,'mpg123'):
      self.mpg123.stop()
    self.stop_event.set()
    self.recorder.stop_recording()
    map(threading.Thread.join,self._threads)
    self._save_state()
    self.debug("... done stopping program")
    sys.exit(0)

  # --- play radio   ----------------------------------------------------------

  def do_play(self):
    """ play radio """

    # start display-controller thread
    self.display.set_content_provider(self.radio)
    self.display.init()
    self._threads.append(self.display)
    self.display.start()

    if options.channel:
      self.radio.func_switch_channel(options.channel)

    # start control-threads
    self._threads.append(self.keypad)
    self.keypad.start()
    self._threads.append(self.lirc)
    self.lirc.start()

# --- main program   ----------------------------------------------------------

if __name__ == '__main__':

  # set local to default from environment
  locale.setlocale(locale.LC_ALL, '')

  # parse commandline-arguments
  opt_parser     = get_parser()
  options        = opt_parser.parse_args(namespace=Options)
  check_options(options)

  app = App(options)

  # setup signal-handler
  signal.signal(signal.SIGTERM, app.signal_handler)
  signal.signal(signal.SIGINT,  app.signal_handler)

  if options.do_list:
    app.radio.print_channels()
  elif options.do_record:
    app.recorder.record(app.radio.get_channel(int(options.channel)-1))
  else:
    app.do_play()
    signal.pause()
