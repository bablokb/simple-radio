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

import locale, os, sys, time, datetime, signal, select, re, shlex
import threading, signal, subprocess, traceback
import Queue, collections
import ConfigParser

try:
  import lcddriver
  have_lcd = True
except:
  print("[WARNING] could not import lcddriver")
  have_lcd = False

FIFO_NAME="/var/run/ttp229-keypad.fifo"
POLL_TIME=2

class Radio(object):
  """ singleton class for all methods of the program """

  def __init__(self):
    """ initialization """

    self._player     = None               # start with no player
    self._channel    = -1                 # and no channel
    self._volume     = -1                 # and unknown volume
    self._name       = ''                 # and no channel-name
    self._disp_queue = Queue.Queue()
    self.stop_event  = threading.Event()

  # --- read configuration   --------------------------------------------------

  def read_config(self,parser):
    """ read configuration from config-file """

    self._i2c    = parser.getint("GLOBAL","i2c")
    self._mixer  = parser.get("GLOBAL","mixer")
    try:
      self._mixer_opts = parser.get("GLOBAL", "mixer_opts")
    except:
      self._mixer_opts = ""

    default_path = os.path.join(os.path.expanduser("~"),"simple-radio.channels")
    try:
      self._channel_file = parser.get("GLOBAL", "channel_file")
    except:
      self._channel_file = default_path

    try:
      self._mpg123_opts = parser.get("GLOBAL", "mpg123_opts")
    except:
      self._mpg123_opts = "-b 1024"

    self._debug       = parser.getboolean("GLOBAL", "debug")
    self.have_disp    = have_lcd and parser.getboolean("DISPLAY", "display")
    self._rows        = parser.getint("DISPLAY", "rows")
    self._cols        = parser.getint("DISPLAY", "cols")
    self._scroll_time = parser.getint("DISPLAY", "scroll")
    self._fmt_title   = u"{0:%d.%ds} {1:5.5s}" % (self._cols-6,self._cols-6)
    self._fmt_line    = u"{0:%d.%ds}" % (self._cols,self._cols)

    # read key-mappings
    self._key_map = {}
    for (key,func_name) in parser.items("KEYS"):
      self._key_map[key] = func_name

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
        channel = channel.rstrip('\n').decode('utf-8')
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
        if not self._name:
          self.debug("clearing lines")
          lines.clear()
        else:
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
        nr = 2
        for line in lines:
          self._lcd.lcd_display_string(line,nr)
          nr += 1
      else:
        # simulate display
        if not self._debug:
          print("\033c")
        print("-%s-" % (self._cols*'-'))
        print("|%s|" % self._get_title())
        for line in lines:
          print("|%s|" % self._fmt_line.format(line))
        print("-%s-" % (self._cols*'-'))

      # sleep
      if self.stop_event.wait(self._scroll_time):
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
      if self.stop_event.wait(0.01):
        break
      poll_result = poll_obj.poll(POLL_TIME*1000)
      for (fd,event) in poll_result:
        # do some sanity checks
        if event & select.POLLHUP == select.POLLHUP:
          # we just wait, continue and hope the key-provider comes back
          if self.stop_event.wait(POLL_TIME):
            break
          continue

        key = pipe.readline().rstrip('\n')
        self.debug("key read: %s" % key)
        if key:
          self.process_key(key)

    # cleanup work after termination
    self.debug("terminating poll_keys on stop request")
    poll_obj.unregister(pipe)
    pipe.close()               # also closes the fd

  # --- read ICY-meta-tags during playback   ----------------------------------

  def read_icy_meta(self):
    """ read ICY-meta-tags of current playback """

    self.debug("starting read_icy_meta")

    regex = re.compile(r".*ICY-META.*?'(.*)';$")
    try:
      while True:
        if not self._name or self._meta_event.wait(0.01):
          self.debug("terminating on stop request")
          break
        data = self._player.stdout.readline().decode('utf-8')
        if data == '' and self._player.poll() is not None:
          break
        if data:
          self.debug("read_icy_meta: data: %s" % data)
          if 'error:' in data:
            line = data.rstrip('\n')
          else:
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
              # hard split within a word
              split = self._cols
              rest  = line[split:]
            else:
              # split at blank: drop blank
              rest  = line[(split+1):]
            self.debug("adding: %s" % line[:split])
            self._disp_queue.put(line[:split])
            line = rest
            self.debug("text left: %s" % line)
          if len(line):
            self._disp_queue.put(line)
          # send separator
          self._disp_queue.put("%s%s" % (((self._cols-6)/2)*' ',6*'*'))

    except:
      # typically an IO-exception due to closing of stdout
      if self._debug:
        traceback.format_exc()
      pass

    # check for error condition (this happens e.g. if the url is wrong)
    if self._name:
      # don't clear lines
      return

    # clear all pending lines
    self.debug("clearing queued lines")
    try:
      count = 0
      while not self._disp_queue.empty():
        count += 1
        self.debug("  ... %d" % count)
        self._disp_queue.get_nowait()
    except:
      if self._debug:
        traceback.format_exc()
      pass

  # --- process key   ---------------------------------------------------------

  def process_key(self,key):
    """ map key to command and execute it"""

    self.debug("processing key %s" % key)
    func_name = self._key_map[key]
    if hasattr(self,func_name):
      self.debug("executing: %s" % func_name)
      func = getattr(self,func_name)
      func(key)

  # --- switch channel   ------------------------------------------------------

  def switch_channel(self,nr):
    """ switch to given channel """

    nr = int(nr)
    self.debug("switch to channel %d" % nr)
    # check if we have to do anything
    if nr == (self._channel+1):
      self.debug("already on channel %d" % nr)
      return
    else:
      self._channel = min(nr-1,len(self._channels)-1)
      channel_name = self._channels[self._channel][0]
      channel_url  = self._channels[self._channel][1]

    # kill current mpg123 process
    self._stop_player()

    # display name of channel on display
    self._name = channel_name

    # spawn new mpg123 process
    args = ["mpg123"]
    opts = shlex.split(self._mpg123_opts)
    args += opts
    if channel_url.endswith(".m3u"):
      args += ["-@",channel_url]
    else:
      args += [channel_url]

    self.debug("starting new channel %s" % self._name)
    self.debug("with args %r" % (args,))
    self._player = subprocess.Popen(args,bufsize=-1,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
    self._meta_event = threading.Event()
    self._meta_thread = threading.Thread(target=self.read_icy_meta)
    self._meta_thread.start()

  # --- switch to next channel   ----------------------------------------------

  def next_channel(self,_):
    """ switch to next channel """

    self.debug("switch to next channel")
    # switch_channel expects a channel-number, while self._channel is
    # a channel index
    self.switch_channel(1+((self._channel+1) % len(self._channels)))

  # --- switch to previous channel   ------------------------------------------

  def prev_channel(self,_):
    """ switch to previous channel """

    self.debug("switch to previous channel")
    # switch_channel expects a channel-number, while self._channel is
    # a channel index
    self.switch_channel(1+((self._channel-1) % len(self._channels)))

  # --- query current volume   ------------------------------------------------

  def _get_volume(self):
    """ query current volume """

    if self._volume != -1:
      return self._volume

    try:
      cmd = ( "amixer %s get %s|grep -o [0-9]*%%|sed 's/%%//'| head -n 1" %
              (self._mixer_opts,self._mixer) )
      self._volume = subprocess.check_output(cmd,shell=True).splitlines()[0]
      self.debug("current volume is: %s%%" % cur_vol)
      return self._volume
    except:
      if self._debug:
        traceback.format_exc()
      return -1

  # --- set volume   ----------------------------------------------------------

  def _set_volume(self,volume):
    """ set volume """

    self.debug("setting volume to %s%%" % volume)
    try:
      args = shlex.split("amixer %s -q set %s %s%%" %
                                       (self._mixer_opts,self._mixer,volume))
      subprocess.call(args)
      self._volume = volume
    except:
      if self._debug:
        traceback.format_exc()

  # --- turn volume up   ------------------------------------------------------

  def volume_up(self,_):
    """ turn volume up """

    self.debug("turn volume up")
    current_volume = self._get_volume()
    self._set_volume(min(current_volume+1,100))

  # --- turn volume down   ----------------------------------------------------

  def volume_down(self,_):
    """ turn volume down """

    self.debug("turn volume down")
    current_volume = self._get_volume()
    self._set_volume(max(current_volume-1,0))

  # --- toggle mute   ---------------------------------------------------------

  def toggle_mute(self,_):
    """ toggle mute """

    self.debug("toggle mute")
    subprocess.call(["amixer","-q","sset",self._mixer,"toggle"])

  # --- turn radio off   ------------------------------------------------------

  def radio_off(self,_):
    """ turn radio off """

    self.debug("turning radio off")
    self._stop_player()

  # --- shutdown system   -----------------------------------------------------

  def shutdown(self,_):
    """ shutdown system """

    self.debug("processing shutdown")
    if not self._debug:
      os.system("sudo /sbin/halt &")
      os.kill(os.getpid(), signal.SIGINT)    # kill ourselves
    else:
      self.debug("no shutdown in debug-mode")

  # --- reboot system   -----------------------------------------------------

  def reboot(self,_):
    """ reboot system """

    self.debug("processing reboot")
    if not self._debug:
      os.system("sudo /sbin/reboot &")
      os.kill(os.getpid(), signal.SIGINT)    # kill ourselves
    else:
      self.debug("no reboot in debug-mode")

  # --- restart system   ------------------------------------------------------

  def restart(self,_):
    """ restart system """

    self.debug("processing restart")
    if not self._debug:
      os.system("sudo /bin/systemctl restart simple-radio.service &")
      os.kill(os.getpid(), signal.SIGINT)    # kill ourselves
    else:
      self.debug("no restart in debug-mode")

  # --- stop player   ---------------------------------------------------------

  def _stop_player(self):
    """ stop current player """

    if self._player:
      self._name = None
      self.debug("stopping player ...")
      try:
        self._player.terminate()
      except:
        if self._debug:
          traceback.format_exc()
        pass
      self._player = None
      self._meta_event.set()
      self._meta_thread.join()
      self._meta_event = None
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

  # set local to default from environment
  locale.setlocale(locale.LC_ALL, '')

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
