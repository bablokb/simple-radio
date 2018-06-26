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

from SRBase   import Base
from SRKeypad import Keypad
from SRRadio  import Radio

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

    self.stop_event = threading.Event()
    self._functions = {}                    # maps user-functions to methods
    self.register_funcs(self.get_funcs())

    self._keypad = Keypad(self)
    self._keypad.read_config()

    self.radio = Radio(self,self._keypad)   # TODO: remove again
    self.radio.read_config()

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

  # --- shutdown system   -----------------------------------------------------

  def func_shutdown(self,_):
    """ shutdown system """

    self.debug("processing shutdown")
    self.radio._stop_mpg123()
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
    self.radio._stop_mpg123()
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
    self.radio._stop_mpg123()
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
    self.radio._stop_mpg123()
    self.stop_event.set()
    if self.radio.rec_stop:
      self.radio.rec_stop.set()
      self.radio._rec_thread.join()
    map(threading.Thread.join,self.radio._threads)
    if self.radio.have_disp:
      self.radio._lcd.lcd_clear()
      self.radio._lcd.lcd_backlight('OFF')
    self.debug("... done stopping program")
    sys.exit(0)

  # --- play radio   ----------------------------------------------------------

  def do_play(self):
    """ play radio """

    # start display-controller thread
    self.radio.init_display()
    display_thread = threading.Thread(target=self.radio.update_display)
    self.radio._threads.append(display_thread)
    display_thread.start()

    if options.channel:
      self.radio.switch_channel(options.channel)

    # start poll keys thread
    self.radio._threads.append(self._keypad)
    self._keypad.start()

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

    self._rec_thread = threading.Thread(target=self.radio.record_stream,
                                     args=(int(options.channel),))
    self.radio.rec_stop = threading.Event()
    self.radio._rec_thread.start()

    if not self.radio.rec_stop.wait(60*self._duration):
      self.radio.rec_stop.set()
    if self.radio._rec_thread.is_alive():
      self.radio._rec_thread.join()

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
