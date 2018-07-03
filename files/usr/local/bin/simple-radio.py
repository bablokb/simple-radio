#!/usr/bin/python
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

import locale, os, sys
from   argparse import ArgumentParser
import threading, signal
import ConfigParser

from SRBase     import Base
from SRKeypad   import Keypad
from SRDisplay  import Display
from SRRadio    import Radio
from SRRecorder import Recorder
from SRPlayer   import Player
from SRMpg123   import Mpg123
from SRAmp      import Amp

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
    print "[ERROR] record-option (-r) needs channel nummber as argument"
    sys.exit(3)

# --- main application class   ----------------------------------------------

class App(Base):
  """ main application class """

  def __init__(self,parser,options):
    """ initialization """

    self.options    = options
    self.parser     = parser
    self.read_config()

    self._threads    = []                   # thread-store
    self.stop_event  = threading.Event()
    self._functions  = {}                   # maps user-functions to methods
    self.register_funcs(self.get_funcs())

    self.keypad = Keypad(self)
    self.keypad.read_config()

    self.radio = Radio(self)
    self.radio.read_config()

    self.player   =  Player(self)
    self.recorder =  Recorder(self)

    self.display = Display(self)
    self.display.read_config()
    self.display.set_content_provider(self.radio)
    self.display.init()

    self.mpg123 = Mpg123(self)
    self.mpg123.read_config()

    self.amp = Amp(self)

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

    if self._functions.has_key(func_name):
      self.debug("executing: %s" % func_name)
      self._functions[func_name](key)

  # --- switch to player mode   -----------------------------------------------

  def func_start_playmode(self,_):
    """ start player mode """

    self.debug("starting player mode")
    self.radio.set_state(False)
    self.mpg123.stop()
    self.keypad.set_keymap(Keypad.KEYPAD_PLAYER)
    self.player.set_state(True)
    self.display.set_content_provider(self.player)

  # --- exit player mode   ----------------------------------------------------

  def func_exit_playmode(self,_):
    """ start player mode """

    self.debug("stopping player mode")
    self.player.set_state(False)
    self.mpg123.stop()
    self.display.clear()
    self.keypad.set_keymap(Keypad.KEYPAD_RADIO)
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

  # --- setup signal handler   ------------------------------------------------

  def signal_handler(self,_signo, _stack_frame):
    """ signal-handler for clean shutdown """

    self.debug("received signal, stopping program ...")
    self.mpg123.stop()
    self.stop_event.set()
    if self.radio.rec_stop:
      self.radio.rec_stop.set()
      self.radio._rec_thread.join()
    map(threading.Thread.join,self._threads)
    self.debug("... done stopping program")
    sys.exit(0)

  # --- play radio   ----------------------------------------------------------

  def do_play(self):
    """ play radio """

    # start display-controller thread
    self._threads.append(self.display)
    self.display.start()

    if options.channel:
      self.radio.switch_channel(options.channel)

    # start poll keys thread
    self._threads.append(self.keypad)
    self.keypad.start()

  # --- list channels   -------------------------------------------------------

  def do_list(self):
    """ list channels """

    LIST_CHANNEL_FMT="{0:2d} {1:14.14s}: {2:s}"
    i = 1
    for channel in self.radio._channels:
      print(LIST_CHANNEL_FMT.format(i,*channel))
      i += 1

  # --- record radio   --------------------------------------------------------

  def do_record(self):
    """ record radio """

    self.recorder.record(self.radio.get_channel(int(options.channel)-1))

# --- main program   ----------------------------------------------------------

if __name__ == '__main__':

  # set local to default from environment
  locale.setlocale(locale.LC_ALL, '')

  # parse commandline-arguments
  opt_parser     = get_parser()
  options        = opt_parser.parse_args(namespace=Options)
  check_options(options)

  parser = ConfigParser.RawConfigParser()
  parser.read('/etc/simple-radio.conf')

  app = App(parser,options)

  # setup signal-handler
  signal.signal(signal.SIGTERM, app.signal_handler)
  signal.signal(signal.SIGINT,  app.signal_handler)

  # read channel-list
  app.radio.read_channels()

  if options.do_list:
    app.do_list()
  elif options.do_record:
    app.do_record()
  else:
    app.do_play()
    signal.pause()
