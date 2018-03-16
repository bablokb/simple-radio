#!/usr/bin/python
# -----------------------------------------------------------------------------
# Simple radio implementation
#   - read channels from file
#   - read keys from pipe and switch channels accordingly
#   - display ICY-META-tags on display
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import os, sys, time, datetime, signal, select, re
import threading, signal, subprocess, traceback
import Queue, collections
import ConfigParser

try:
  import lcddriver
  have_disp = True
except:
  print("[WARNING] could not import lcddriver")
  have_disp = False

FIFO_NAME="/var/run/ttp229-keypad.fifo"
POLL_TIME=5
SCROLL_TIME=3

class Radio(object):
  """ singleton class for all methods of the program """

  def __init__(self):
    """ initialization """

    self._player     = None               # start with no player
    self._channel    = -1                 # and no channel
    self._name       = ''                 # and no channel-name
    self._disp_queue = Queue.Queue()
    self.stop_event  = threading.Event()

  # --- read configuration   --------------------------------------------------

  def read_config(self,parser):
    """ read configuration from config-file """

    self._i2c = parser.getint("GLOBAL","i2c")
    default_path = os.path.join(os.path.expanduser("~"),"simple-radio.channels")
    try:
      self._channel_file = parser.get("GLOBAL", "channel_file")
    except:
      self._channel_file = default_path

    self._debug     = parser.getboolean("GLOBAL", "debug")
    self.have_disp  = have_disp and parser.getboolean("DISPLAY", "display")
    self._rows      = parser.getint("DISPLAY", "rows")
    self._cols      = parser.getint("DISPLAY", "cols")
    self._fmt_title = u"{0:%d.%ds} {1:5.5s}" % (self._cols-6,self._cols-6)
    self._fmt_line  = u"{0:%d.%ds}" % (self._cols,self._cols)

  # --- print debug messages   ------------------------------------------------

  def debug(self,text):
    """ print debug-message """

    if self._debug:
      sys.stderr.write("[DEBUG] %s\n" % text)
      sys.stderr.flush()

  # --- read channels   -------------------------------------------------------

  def read_channels(self):
    """ read channels into a list """

    self._channels = []
    with open(self._channel_file) as f:
      for channel in f:
        channel = channel.decode('utf-8')
        self._channels.append(channel.split('@')) # channel: line with name@url

  # --- get title-line (1st line of display)   -------------------------------

  def _get_title(self):
    """ return title-line (1st line of display) """

    now = datetime.datetime.now()
    if not self._name:
      # return date + time
      return self._fmt_title.format(now.strftime("%x"),now.strftime("%X"))
    else:
      # return channel-name + time
      return self._fmt_title.format(self._name,now.strftime("%X"))


  # --- initialize display   -------------------------------------------------

  def init_display(self):
    """ initialize display """

    # initialize hardware
    try:
      self._lcd = lcddriver.lcd(port=self._i2c)
      self._lcd.lcd_display_string(self._get_title(),1)
    except:
      self.debug("no display detected")
      self.have_disp = False
      if self._debug:
        traceback.format_exc()
      pass
    
  # --- display-controller thread    -----------------------------------------

  def update_display(self):
    """ display-controller-thread """

    self.debug("starting update_display")

    lines = collections.deque(maxlen=self._rows-1)
    while True:
      # poll queue for data and append to deque
      try:
        line = self._disp_queue.get_nowait()
        self.debug("update_display: line: %s" % line)
        lines.append(line)
      except:
        if self._debug:
          traceback.format_exc()
        pass

      # write data to display
      if self.have_disp:
        self._lcd.lcd_display_string(self._get_title(),1)
        # TODO: fix!!
        for i in range(2,min(self._rows+1,len(lines)-1)):
          self._lcd.lcd_display_string(lines[i-2],i)
        # TODO: fix!!
      else:
        # simulate display
        if not self._debug:
          print("\033c")
        print("|%s|" % (self._cols*'-'))
        print("|%s|" % self._get_title())
        for line in lines:
          print("|%s|" % self._fmt_line.format(line))
        print("|%s|" % (self._cols*'-'))

      # sleep
      if self.stop_event.wait(SCROLL_TIME):
        self.debug("terminating update_display on stop request")
        return

  # --- poll keys   ---------------------------------------------------------

  def poll_keys(self):
    """ poll keys from pipe """

    self.debug("starting poll_keys")

    # wait for pipe
    pipe_wait = 0.5
    while not os.path.exists(FIFO_NAME):
      self.debug("waiting for pipe ...")
      if pipe_wait < POLL_TIME/2:
        pipe_wait *= 2
      if self.stop_event.wait(pipe_wait):
        # program ended, before we actually started
        return

    # make sure the open call does not block
    p_fd = os.open(FIFO_NAME,os.O_RDONLY|os.O_NONBLOCK)
    pipe = os.fdopen(p_fd,"r")
    poll_obj = select.poll()
    poll_obj.register(p_fd,select.POLLPRI|select.POLLIN)

    # main loop
    while True:
      poll_result = poll_obj.poll(POLL_TIME*1000)
      for (fd,event) in poll_result:
        # do some sanity checks
        if event & select.POLLHUP == select.POLLHUP:
          if self.stop_event.wait(POLL_TIME):
            break
          # we just continue and hope the key-provider comes back
          continue

      key = pipe.readline()
      self.debug("key read: %s" % key)
      if key:
        self.process_key(key)
      if self.stop_event.wait(0.01):
        break

    # cleanup work after termination
    self.debug("terminating poll_keys on stop request")
    poll_obj.unregister(pipe)
    pipe.close()               # also closes the fd

  # --- read ICY-meta-tags during playback   ----------------------------------

  def read_icy_meta(self):
    """ read ICY-meta-tags of current playback """

    self.debug("starting read_icy_meta")

    regex = re.compile(r".*ICY-META.*'([^']*)';")
    try:
      while True:
        if self._meta_event.wait(0.01):
          return
        data = self._player.stdout.readline().decode('utf-8')
        if data == '' and self._player.poll() is not None:
          break
        if data:
          self.debug("read_icy_meta: data: %s" % data)
          # parse line
          (line,count) = regex.subn(r'\1',data)
          if not count:
            self.debug("ignoring data")
            continue
          else:
            line = line.rstrip('\n')

          # break line in parts
          self.debug("splitting line: %s" % line)
          while len(line) > self._cols:
            split = line[:self._cols].rfind(" ")
            self.debug("split: %d" % split)
            if split == -1:
              split = self._cols
            self.debug("adding: %s" % line[:split])
            self._disp_queue.put(line[:split])
            line = line[(split+1):]
            self.debug("text left: %s" % line)
          if len(line):
            self._disp_queue.put(line)
    except:
      # typically an IO-exception due to closing of stdout
      if self._debug:
        traceback.format_exc()
      pass

  # --- process key   ---------------------------------------------------------

  def process_key(self,key):
    """ process key: switch to given channel """

    self.debug("processing key %s" % key)
    key = int(key)                       # for LIRC, map LIRC-name to key
    # check if we have to do anything
    if key == self._channel:
      return
    else:
      self._channel = min(key-1,len(self._channels)-1)
      channel_name = self._channels[self._channel][0]
      channel_url  = self._channels[self._channel][1]

    # kill current mpg123 process
    self._stop_player()

    # display name of channel on display
    self._name = channel_name

    # spawn new mpg123 process
    args = ["mpg123","-b","1024","-@",channel_url]

    self.debug("starting new channel %s" % self._name)
    self._player = subprocess.Popen(args,bufsize=-1,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
    self._meta_event = threading.Event()
    self._meta_thread = threading.Thread(target=self.read_icy_meta)
    self._meta_thread.start()

  # --- stop player   ---------------------------------------------------------

  def _stop_player(self):
    """ stop current player """

    if self._player:
      self.debug("stopping player ...")
      self._player.terminate()
      self._player = None
      self._meta_event.set()
      self._meta_thread.join()
      self._meta_event = None
      self._name = None
      self.debug("... done stopping player")
    
  # --- setup signal handler   ------------------------------------------------

  def signal_handler(self,_signo, _stack_frame):
    """ signal-handler for clean shutdown """

    self.debug("received signal, stopping program ...")
    self._stop_player()
    self.stop_event.set()
    map(threading.Thread.join,[self.display_thread,self.key_thread])
    self.debug("... done stopping program")
    sys.exit(0)

# --- main program   ----------------------------------------------------------

if __name__ == '__main__':

  radio = Radio()

  # read configuration
  parser = ConfigParser.RawConfigParser()
  parser.read('/etc/simple-radio.conf')
  radio.read_config(parser)

  # setup signal-handler
  signal.signal(signal.SIGTERM, radio.signal_handler)
  signal.signal(signal.SIGINT, radio.signal_handler)

  # read channel-list
  radio.read_channels()

  # start display-controller thread
  radio.init_display()
  radio.display_thread = threading.Thread(target=radio.update_display)
  radio.display_thread.start()

  # start poll keys thread
  radio.key_thread = threading.Thread(target=radio.poll_keys)
  radio.key_thread.start()

  # main loop (wait for termination)
  signal.pause()
