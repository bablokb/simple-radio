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

import locale, os, sys, time, datetime, signal, select, re, shlex
from   argparse import ArgumentParser
import threading, signal, subprocess, traceback
import Queue, collections
import ConfigParser, urllib2

from SRBase   import Base
from SRKeypad import Keypad

try:
  import lcddriver
  have_lcd = True
except ImportError:
  print("[WARNING] could not import lcddriver")
  have_lcd = False

RECORD_CHUNK = 65536                 # with 128kbs, this should be around 4s

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

class Radio(Base):
  """ singleton class for all methods of the program """

  def __init__(self,parser):
    """ initialization """

    self._parser       = parser
    self._mpg123       = None               # start with no player
    self._radio_mode   = True               # default is radio
    self._channel      = -1                 # and no channel
    self._volume       = -1                 # and unknown volume
    self._name         = ''                 # and no channel-name
    self._threads      = []                 # thread-store
    self._disp_queue   = Queue.Queue()
    self.stop_event    = threading.Event()
    self.rec_stop      = None
    self._rec_channel  = None
    self._rec_start_dt = None
    self._recordings   = None
    self._rec_show     = True               # toggle: show rec_channel or normal
                                            #         title
    self._keypad       = Keypad(self,parser,self.stop_event)
    self._keypad.read_config()

  # --- read configuration   --------------------------------------------------

  def read_config(self):
    """ read configuration from config-file """

    # section [GLOBAL]
    self._debug  = self.get_value(self._parser,"GLOBAL", "debug","0") == "1"
    self._i2c    = int(self.get_value(self._parser,"GLOBAL","i2c",0))
    self._mixer  = self.get_value(self._parser,"GLOBAL","mixer","PCM")
    self._mixer  = self.get_value(self._parser,"GLOBAL","mixer_opts","")

    default_path        = os.path.join(os.path.expanduser("~"),
                                       "simple-radio.channels")
    self._channel_file  = self.get_value(self._parser,"GLOBAL","channel_file",
                                         default_path)
    self._mpg123_opts   = self.get_value(self._parser,"GLOBAL", "mpg123_opts","-b 1024")

    # section [DISPLAY]
    have_disp         = self.get_value(self._parser,"DISPLAY", "display","0") == "1"
    self.have_disp    = have_lcd and have_disp
    self._rows        = int(self.get_value(self._parser,"DISPLAY", "rows",2))
    self._cols        = int(self.get_value(self._parser,"DISPLAY", "cols",16))
    self._scroll_time = int(self.get_value(self._parser,"DISPLAY", "scroll",3))
    rule              = self.get_value(self._parser,"DISPLAY","trans",None)
    if rule:
      rule            = rule.split(",")
      rule[0]         = rule[0].decode('UTF-8')
      self._transmap  = self.build_map(rule)
    else:
      self._transmap  = None
    self._radio_fmt_title = u"{0:%d.%ds} {1:5.5s}" % (self._cols-6,self._cols-6)
    self._rec_fmt_title   = u"{0:%d.%ds} {1:02d}*{2:02d}" % (self._cols-6,self._cols-6)
    self._fmt_line        = u"{0:%d.%ds}" % (self._cols,self._cols)
    self._play_fmt_title = u"{0:%d.%ds}{1:5.5s}/{2:5.5s}" % (self._cols-11,self._cols-11)

    # section [RECORD]
    if not options.target_dir is None:
      self._target_dir = options.target_dir[0]
    else:
      self._target_dir = self.get_value(self._parser,"RECORD","dir",
                                        os.path.expanduser("~"))
    if not os.path.exists(self._target_dir):
      os.mkdir(self._target_dir)
    elif not os.path.isdir(self._target_dir):
      print("[ERROR] target-directory for recordings %s is not a directory" %
            self._target_dir)

    if options.duration:
      self._duration = int(options.duration)
    else:
      self._duration = int(self.get_value(self._parser,"RECORD","duration",60))

  # --- build translation map for display   -----------------------------------

  def build_map(self,rule):
    map = {}
    for i in range(len(rule[0])):
      map[rule[0][i]] = int(rule[i+1],16)
    return map

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
    if self._name and self._rec_start_dt:
      # listening radio and ongoing recording: toggle title-line
      if self._rec_show:
        self._rec_show = False
        return self._get_rec_title(now - self._rec_start_dt)
      else:
        self._rec_show = True
        return self._radio_fmt_title.format(self._name,now.strftime("%X"))
    elif self._name:
      # no recording, just show current channel
      return self._radio_fmt_title.format(self._name,now.strftime("%X"))
    elif self._rec_start_dt:
      # only recording: show channel and duration
      return self._get_rec_title(now - self._rec_start_dt)
    else:
      # return date + time
      return self._radio_fmt_title.format(now.strftime("%x"),now.strftime("%X"))

  # --- get title for recordings   -------------------------------------------

  def _get_rec_title(self,duration):
    """ get title during recordings """

    duration = int(duration.total_seconds())
    m, s = divmod(duration,60)
    h, m = divmod(m,60)

    # check if we have to stop recording
    # actually, wie should do this in update_display, but here we have all
    # the necessary information
    if m >= self._duration and self.rec_stop:
      self.rec_stop.set()

    # return either mm:ss or hh:mm
    if h > 0:
      return self._rec_fmt_title.format(self._rec_channel,h,m)
    else:
      return self._rec_fmt_title.format(self._rec_channel,m,s)

  # --- initialize display   -------------------------------------------------

  def init_display(self):
    """ initialize display """

    # initialize hardware
    try:
      self._lcd = lcddriver.lcd(port=self._i2c,tmap=self._transmap)
      self._lcd.lcd_display_string(self._get_title(),1)
    except:
      self.debug("no display detected")
      self.have_disp = False
      if self._debug:
        print traceback.format_exc()
      pass
    
  # --- display-controller thread    -----------------------------------------

  def update_display(self):
    """ display-controller-thread """

    self.debug("starting update_display")

    lines = collections.deque(maxlen=self._rows-1)
    while True:
      if self._radio_mode:
        self._write_display_radio(lines)
      else:
        if not self._mpg123 is None and not self._mpg123.poll() is None:
          self.stop_play("_")
        self._write_display_player()

      # sleep
      if self.stop_event.wait(self._scroll_time):
        self.debug("terminating update_display on stop request")
        return

  # --- write to the display (radio mode)   ---------------------------------

  def _write_display_radio(self,lines):
    """ write to the display (radio mode) """

    # poll queue for data and append to deque
    try:
      for  i in range(self._rows-1):
        line = self._disp_queue.get_nowait()
        self.debug("update_display: line: %s" % line)
        lines.append(line)
    except Queue.Empty:
      pass
    except:
      if self._debug:
        print traceback.format_exc()
    self._write_display(self._get_title(),lines)

  # --- write to the display   ----------------------------------------------

  def _write_display(self,title, lines):
    """ write to the display """

    # clear screen in simulation-mode (unless debugging)
    if not self.have_disp and not self._debug:
      print("\033c")

    # write data to display
    if self.have_disp:
      self._lcd.lcd_display_string(title,1)
      nr = 2
      for line in lines:
        self._lcd.lcd_display_string(self._fmt_line.format(line),nr)
        nr += 1
    else:
      # simulate display
      print("-%s-" % (self._cols*'-'))
      print("|%s|" % title)
      for line in lines:
        print("|%s|" % self._fmt_line.format(line))
      print("-%s-" % (self._cols*'-'))

  # --- write to the display (player mode)   --------------------------------

  def _write_display_player(self):
    """ write to the display (player mode) """

    lines=[]

    # check if currently are reading the recordings
    if self._rec_index is None and self._recordings:
      tile = "reading"
      lines.append("recordings ...")
      self._write_display(title,lines)
      return

    # parse filename
    if not self._rec_index is None:
      (_,rec) = os.path.split(self._recordings[self._rec_index])
      (rec,_) = os.path.splitext(rec)
      [date,time,channel] = rec.split("_")
      date = "%s.%s.%s" % (date[6:8],date[4:6],date[0:4])
      time = "%s:%s" % (time[0:2],time[2:4])

    if not self._mpg123:
      # nothing is playing, show current recording
      if self._rec_index is None:
        title = 'no recordings'
      else:
        title = "%s %s" % (time,date)
        lines.append(channel)
    else:
      # show progress
      if self._play_pause:
        curtime = self._play_pause_dt - self._play_start_dt
      else:
        curtime = datetime.datetime.now() - self._play_start_dt
      curtime = self._pp_time(int(curtime.total_seconds()))

      if self._play_pause:
        title = self._play_fmt_title.format('pause',curtime,self._play_tottime)
      else:
        title = self._play_fmt_title.format('>>>>',curtime,self._play_tottime)
      lines.append(channel)
      if self._rows > 2:
        lines.append("%s %s" % (time,date))
    self._write_display(title,lines)

  # --- pretty print duration/time   ----------------------------------------

  def _pp_time(self,seconds):
    """ pritty-print time as mm:ss or hh:mm """

    m, s = divmod(seconds,60)
    h, m = divmod(m,60)
    if h > 0:
      return "{0:02d}:{1:02d}".format(h,m)
    else:
      return "{0:02d}:{1:02d}".format(m,s)

  # --- read ICY-meta-tags during playback   ----------------------------------

  def read_icy_meta(self):
    """ read ICY-meta-tags of current playback """

    self.debug("starting read_icy_meta")

    regex = re.compile(r".*ICY-META.*?'(.*)';$")
    try:
      while True:
        if not self._name or self._mpg123_event.wait(0.01):
          self.debug("terminating on stop request")
          break
        data = self._mpg123.stdout.readline().decode('utf-8')
        if data == '' and self._mpg123.poll() is not None:
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
        print traceback.format_exc()
      pass

    # check for error condition (this happens e.g. if the url is wrong)
    if self._name:
      # don't clear lines
      return

    # clear all pending lines
    self.debug("clearing queued lines ...")
    try:
      count = 0
      while not self._disp_queue.empty():
        count += 1
        self.debug("  ... %d" % count)
        self._disp_queue.get_nowait()
    except:
      if self._debug:
        print traceback.format_exc()
      pass
    self.debug("... and clearing lines on the display")
    for i in range(self._rows-1):
      self._disp_queue.put(" ")

  # --- record stream   -------------------------------------------------------

  def record_stream(self,nr):
    """ record the given stream """

    [ self._rec_channel,url ] = self._channels[nr-1]
    request = urllib2.Request(url)
    cur_dt_string = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = "%s%s%s_%s" % (self._target_dir,os.sep,cur_dt_string,
                                                             self._rec_channel)

    content_type = request.get_header('Content-Type')
    if(content_type == 'audio/mpeg'):
      filename += '.mp3'
    elif(content_type == 'application/ogg' or content_type == 'audio/ogg'):
      filename += '.ogg'
    elif(content_type == 'audio/x-mpegurl'):
      url = None
      conn = urllib2.urlopen(request)
      with conn as stream:
        if not line.decode('utf-8').startswith('#') and len(line) > 1:
          url = line.decode('utf-8')
          stream.close()
      if url:
        request = urllib2.Request(url)
        filename += '.mp3'
      else:
        self._debug("could not parse m3u-playlist")
        return
    else:
      self.debug('unknown content type %r. Assuming mp3' % content_type)
      filename += '.mp3'

    with open(filename, "wb") as stream:
      self.debug('recording %s for %d minutes' %
                                              (self._rec_channel,self._duration))
      conn = urllib2.urlopen(request)
      self._rec_start_dt = datetime.datetime.now()
      while(not self.rec_stop.is_set()):
        stream.write(conn.read(RECORD_CHUNK))

    self.debug('recording finished')
    self.rec_stop.set()

  # --- switch channel   ------------------------------------------------------

  def switch_channel(self,nr):
    """ switch to given channel """

    nr = int(nr)
    self.debug("switch to channel %d" % nr)
    # check if we have to do anything
    if nr == (self._channel+1):
      self.debug("already on channel %d" % nr)
      return

    # kill current mpg123 process
    self._stop_mpg123()

    self._channel = min(nr-1,len(self._channels)-1)
    channel_name = self._channels[self._channel][0]
    channel_url  = self._channels[self._channel][1]

    # display name of channel on display
    self._name = channel_name
    self.debug("starting new channel %s" % self._name)
    self._start_mpg123(channel_url)

  # --- start to play music   ------------------------------------------------

  def _start_mpg123(self,name):
    """ spawn new mpg123 process """

    args = ["mpg123"]
    opts = shlex.split(self._mpg123_opts)
    args += opts
    if name.endswith(".m3u"):
      args += ["-@",name]
    else:
      args += [name]

    self.debug("with args %r" % (args,))
    self._mpg123 = subprocess.Popen(args,bufsize=1,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
    if self._radio_mode:
      self._mpg123_event = threading.Event()
      self._mpg123_thread = threading.Thread(target=self.read_icy_meta)
      self._mpg123_thread.start()

  # --- switch to next channel   ----------------------------------------------

  def next_channel(self,_):
    """ switch to next channel """

    self.debug("switch to next channel")
    # switch_channel expects a channel-number, while self._channel is
    # a channel index
    if self._channel == -1:
      self.switch_channel(1)
    else:
      self.switch_channel(1+((self._channel+1) % len(self._channels)))

  # --- switch to previous channel   ------------------------------------------

  def prev_channel(self,_):
    """ switch to previous channel """

    self.debug("switch to previous channel")
    # switch_channel expects a channel-number, while self._channel is
    # a channel index
    if self._channel == -1:
      self.switch_channel(len(self._channels))
    else:
      self.switch_channel(1+((self._channel-1) % len(self._channels)))

  # --- toggle recording   ----------------------------------------------------

  def toggle_record(self,_):
    """ toggle recording """

    self.debug("toggle recording")

    if self.rec_stop:
      # recording is ongoing, so stop it
      self.rec_stop.set()
      self._rec_thread.join()
      self.rec_stop = None
      self._rec_start_dt = None
    else:
      # no recording ongoing, start it
      self._rec_thread = threading.Thread(target=radio.record_stream,
                                     args=(self._channel+1,))
      self.rec_stop = threading.Event()
      self._rec_thread.start()

  # --- switch to player mode   -----------------------------------------------

  def start_playmode(self,_):
    """ start player mode """

    self.debug("starting player mode")
    self._stop_mpg123()
    self._radio_mode = False
    self._play_start_dt = None
    self._read_recordings()
    self._keypad.set_keymap(Keypad.KEYPAD_PLAYER)

  # --- toggle play/pause   ---------------------------------------------------

  def toggle_play(self,_):
    """ toggle play/pause """

    if self._play_start_dt == None:
      if not self._rec_index is None:
        self.debug("starting playback")
        total_secs = int(subprocess.check_output(["mp3info", "-p","%S",
                                            self._recordings[self._rec_index]]))
        self._play_tottime = self._pp_time(total_secs)
        self._play_pause = False
        self._play_start_dt = datetime.datetime.now()
        self._start_mpg123(self._recordings[self._rec_index])
    elif not self._play_pause:
      self.debug("pausing playback")
      self._play_pause = True
      self._mpg123.send_signal(signal.SIGSTOP)
      self._play_pause_dt = datetime.datetime.now()
    else:
      self.debug("continuing playback")
      self._play_pause = False
      now = datetime.datetime.now()
      self._play_start_dt += (now-self._play_pause_dt)
      self._mpg123.send_signal(signal.SIGCONT)

  # --- stop playing ----------------------------------------------------------

  def stop_play(self,_):
    """ stop playing """

    self.debug("stopping playback")
    self._stop_mpg123()
    self._play_start_dt = None

  # --- previous recording   --------------------------------------------------

  def prev_recording(self,_):
    """ switch to previous recording """

    if self._play_start_dt == None:
      self.debug("switch to previous recording")
      if self._rec_index is None:
        return
      else:
        self._rec_index = (self._rec_index-1) % len(self._recordings)
        self.debug("current recording: %s" % self._recordings[self._rec_index])
    else:
      self.debug("playback in progress, ignoring command")

  # --- next recording   -------------------------------------------------------

  def next_recording(self,_):
    """ switch to next recording """

    if self._play_start_dt == None:
      self.debug("switch to next recording")
      if self._rec_index is None:
        return
      else:
        self._rec_index = (self._rec_index+1) % len(self._recordings)
        self.debug("current recording: %s" % self._recordings[self._rec_index])
    else:
      self.debug("playback in progress, ignoring command")

  # --- exit player mode   ----------------------------------------------------

  def exit_playmode(self,_):
    """ start player mode """

    self.debug("stopping player mode")
    self._stop_mpg123()
    self._play_start_dt = None
    if self.have_disp:
      self._lcd.lcd_clear()
    self._rec_index  = None
    self._recordings = None
    self._radio_mode = True
    self._keypad.set_keymap(Keypad.KEYPAD_RADIO)

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
    self._stop_mpg123()

  # --- shutdown system   -----------------------------------------------------

  def shutdown(self,_):
    """ shutdown system """

    self.debug("processing shutdown")
    self._stop_mpg123()
    if not self._debug:
      try:
        os.system("sudo /sbin/halt &")
      except:
        pass
    else:
      self.debug("no shutdown in debug-mode")

  # --- reboot system   -----------------------------------------------------

  def reboot(self,_):
    """ reboot system """

    self.debug("processing reboot")
    self._stop_mpg123()
    if not self._debug:
      try:
        os.system("sudo /sbin/reboot &")
      except:
        pass
    else:
      self.debug("no reboot in debug-mode")

  # --- restart system   ------------------------------------------------------

  def restart(self,_):
    """ restart system """

    self.debug("processing restart")
    self._stop_mpg123()
    if not self._debug:
      try:
        os.system("sudo /bin/systemctl restart simple-radio.service &")
      except:
        pass
    else:
      self.debug("no restart in debug-mode")

  # --- read existing recordings   --------------------------------------------

  def _read_recordings(self):
    """ read recordings from configured directory """

    self.debug("reading recordings")

    self._recordings = []
    for f in os.listdir(self._target_dir):
      rec_file = os.path.join(self._target_dir,f)
      if not os.path.isfile(rec_file):
        continue
      # check extension
      (_,ext) = os.path.splitext(rec_file)
      if ext in [".mp3",".ogg",".wav"]:
        self._recordings.append(rec_file)

    if len(self._recordings):
      self._recordings.sort()
      self._rec_index  = len(self._recordings)-1
    else:
      self._rec_index  = None

  # --- stop player   ---------------------------------------------------------

  def _stop_mpg123(self):
    """ stop current player """

    if self._mpg123:
      self._name = None
      self._channel = -1
      self.debug("stopping player ...")
      try:
        self._mpg123.terminate()
      except:
        pass
      self._mpg123 = None
      if self._radio_mode:
        self._mpg123_event.set()
        self._mpg123_thread.join()
        self._mpg123_event = None
      self.debug("... done stopping player")
    
  # --- setup signal handler   ------------------------------------------------

  def signal_handler(self,_signo, _stack_frame):
    """ signal-handler for clean shutdown """

    self.debug("received signal, stopping program ...")
    self._stop_mpg123()
    self.stop_event.set()
    if self.rec_stop:
      self.rec_stop.set()
      self._rec_thread.join()
    map(threading.Thread.join,self._threads)
    if self.have_disp:
      self._lcd.lcd_clear()
      self._lcd.lcd_backlight('OFF')
    self.debug("... done stopping program")
    sys.exit(0)

  # --- play radio   ----------------------------------------------------------

  def do_play(self):
    """ play radio """

    # start display-controller thread
    self.init_display()
    display_thread = threading.Thread(target=radio.update_display)
    self._threads.append(display_thread)
    display_thread.start()

    if options.channel:
      self.switch_channel(options.channel)

    # start poll keys thread
    self._threads.append(self._keypad)
    self._keypad.start()

  # --- list channels   -------------------------------------------------------

  def do_list(self):
    """ list channels """

    LIST_CHANNEL_FMT="{0:2d} {1:14.14s}: {2:s}"
    i = 1
    for channel in self._channels:
      print(LIST_CHANNEL_FMT.format(i,*channel))
      i += 1

  # --- record radio   --------------------------------------------------------

  def do_record(self):
    """ record radio """

    self._rec_thread = threading.Thread(target=radio.record_stream,
                                     args=(int(options.channel),))
    self.rec_stop = threading.Event()
    self._rec_thread.start()

    if not self.rec_stop.wait(60*self._duration):
      self.rec_stop.set()
    if self._rec_thread.is_alive():
      self._rec_thread.join()

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

  radio = Radio(parser)
  radio.read_config()

  # setup signal-handler
  signal.signal(signal.SIGTERM, radio.signal_handler)
  signal.signal(signal.SIGINT, radio.signal_handler)

  # read channel-list
  radio.read_channels()

  if options.do_list:
    radio.do_list()
  elif options.do_record:
    radio.do_record()
  else:
    radio.do_play()
    signal.pause()
