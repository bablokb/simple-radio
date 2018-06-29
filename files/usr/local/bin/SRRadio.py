#!/usr/bin/python
# -----------------------------------------------------------------------------
# Simple radio: implementation of class Radio
#
# The class Radio implements the core functionality of simple radio
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import threading, os, time, datetime, shlex
import Queue, collections
import threading, signal, subprocess, traceback
import urllib2

from SRBase import Base
from SRKeypad import Keypad

RECORD_CHUNK = 65536                 # with 128kbs, this should be around 4s


class Radio(Base):
  """ Radio-controller """

  def __init__(self,app):
    """ initialization """

    self._app          = app
    app.register_funcs(self.get_funcs())

    self._keypad       = app.keypad         # TODO: remove again
    self._radio_mode   = True               # default is radio
    self._channel      = -1                 # and no channel
    self._volume       = -1                 # and unknown volume
    self._name         = ''                 # and no channel-name
    self.stop_event    = app.stop_event
    self.rec_stop      = None
    self._rec_channel  = None
    self._rec_start_dt = None
    self._recordings   = None
    self._rec_show     = True               # toggle: show rec_channel or normal
                                            #         title

  # --- read configuration   --------------------------------------------------

  def read_config(self):
    """ read configuration from config-file """

    # section [GLOBAL]
    self._debug       = self.get_value(self._app.parser,"GLOBAL", "debug","0") == "1"
    self._mixer       = self.get_value(self._app.parser,"GLOBAL","mixer","PCM")
    self._mixer_opts  = self.get_value(self._app.parser,"GLOBAL","mixer_opts","")

    default_path        = os.path.join(os.path.expanduser("~"),
                                       "simple-radio.channels")
    self._channel_file  = self.get_value(self._app.parser,"GLOBAL","channel_file",
                                         default_path)

    # section [DISPLAY]
    self._rows        = int(self.get_value(self._app.parser,"DISPLAY", "rows",2))
    self._cols        = int(self.get_value(self._app.parser,"DISPLAY", "cols",16))

    self._play_fmt_title = u"{0:%d.%ds}{1:5.5s}/{2:5.5s}" % (self._cols-11,self._cols-11)

    # section [RECORD]
    if not self._app.options.target_dir is None:
      self._target_dir = self._app.options.target_dir[0]
    else:
      self._target_dir = self.get_value(self._app.parser,"RECORD","dir",
                                        os.path.expanduser("~"))
    if not os.path.exists(self._target_dir):
      os.mkdir(self._target_dir)
    elif not os.path.isdir(self._target_dir):
      print("[ERROR] target-directory for recordings %s is not a directory" %
            self._target_dir)

    if self._app.options.duration:
      self._duration = int(self._app.options.duration)
    else:
      self._duration = int(self.get_value(self._app.parser,"RECORD","duration",60))

  # --- read channels   -------------------------------------------------------

  def read_channels(self):
    """ read channels into a list """

    self._channels = []
    with open(self._channel_file) as f:
      for channel in f:
        channel = channel.rstrip('\n').decode('utf-8')
        self._channels.append(channel.split('@')) # channel: line with name@url

  # --- get title-line (1st line of display)   -------------------------------

  def get_title(self):
    """ return title-line (1st line of display) """

    now = datetime.datetime.now()
    if self._name and self._rec_start_dt:
      # listening radio and ongoing recording: toggle title-line
      if self._rec_show:
        self._rec_show = False
        return self._get_rec_title(now - self._rec_start_dt)
      else:
        self._rec_show = True
        return (self._name,now.strftime("%H:%M"))
    elif self._name:
      # no recording, just show current channel
      return (self._name,now.strftime("%H:%M"))
    elif self._rec_start_dt:
      # only recording: show channel and duration
      return self._get_rec_title(now - self._rec_start_dt)
    else:
      # return date + time
      return (now.strftime("%x"),now.strftime("%H:%M"))

  # --- get title for recordings   -------------------------------------------

  def _get_rec_title(self,duration):
    """ get title during recordings """

    duration = int(duration.total_seconds())
    m, s = divmod(duration,60)
    h, m = divmod(m,60)

    # check if we have to stop recording
    # actually, wie should do this elsewhere, but here we have all
    # the necessary information
    if m >= self._duration and self.rec_stop:
      self.rec_stop.set()

    # return either mm:ss or hh:mm
    if h > 0:
      return (self._rec_channel,u"{0:02d}*{1:02d}".format(h,m))
    else:
      return (self._rec_channel,u"{0:02d}*{1:02d}".format(m,s))

  # --- get content for display   -------------------------------------------

  def get_content(self):
    """ read icy-data if available """

    lines = []
    if self._app.mpg123.icy_data:
      while True:
        try:
          line = self._app.mpg123.icy_data.get_nowait()
          self.debug("get_content: line: %s" % line)
          lines.append(line)
        except Queue.Empty:
          break
        except:
          if self._debug:
            print traceback.format_exc()
          break
    return lines

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

    if not self._app.mpg123.is_active():
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

  def func_switch_channel(self,nr):
    """ switch to given channel """

    nr = int(nr)
    self.debug("switch to channel %d" % nr)
    # check if we have to do anything
    if nr == (self._channel+1):
      self.debug("already on channel %d" % nr)
      return

    # kill current mpg123 process
    self._name = None
    self._channel = -1
    self._app.mpg123.stop()

    self._channel = min(nr-1,len(self._channels)-1)
    channel_name = self._channels[self._channel][0]
    channel_url  = self._channels[self._channel][1]

    # display name of channel on display
    self._name = channel_name
    self.debug("starting new channel %s" % self._name)
    self._app.mpg123.start(channel_url,True)

  # --- switch to next channel   ----------------------------------------------

  def func_next_channel(self,_):
    """ switch to next channel """

    self.debug("switch to next channel")
    # switch_channel expects a channel-number, while self._channel is
    # a channel index
    if self._channel == -1:
      self.switch_channel(1)
    else:
      self.switch_channel(1+((self._channel+1) % len(self._channels)))

  # --- switch to previous channel   ------------------------------------------

  def func_prev_channel(self,_):
    """ switch to previous channel """

    self.debug("switch to previous channel")
    # switch_channel expects a channel-number, while self._channel is
    # a channel index
    if self._channel == -1:
      self.switch_channel(len(self._channels))
    else:
      self.switch_channel(1+((self._channel-1) % len(self._channels)))

  # --- toggle recording   ----------------------------------------------------

  def func_toggle_record(self,_):
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
      self._rec_thread = threading.Thread(target=self.record_stream,
                                     args=(self._channel+1,))
      self.rec_stop = threading.Event()
      self._rec_thread.start()

  # --- switch to player mode   -----------------------------------------------

  def func_start_playmode(self,_):
    """ start player mode """

    self.debug("starting player mode")
    self._name = None
    self._channel = -1
    self._app.mpg123.stop()
    self._radio_mode = False
    self._play_start_dt = None
    self._read_recordings()
    self._keypad.set_keymap(Keypad.KEYPAD_PLAYER)

  # --- toggle play/pause   ---------------------------------------------------

  def func_toggle_play(self,_):
    """ toggle play/pause """

    if self._play_start_dt == None:
      if not self._rec_index is None:
        self.debug("starting playback")
        total_secs = int(subprocess.check_output(["mp3info", "-p","%S",
                                            self._recordings[self._rec_index]]))
        self._play_tottime = self._pp_time(total_secs)
        self._play_pause = False
        self._play_start_dt = datetime.datetime.now()
        self._app.mpg123.start(self._recordings[self._rec_index],False)
    elif not self._play_pause:
      self._play_pause = True
      self._app.mpg123.pause()
      self._play_pause_dt = datetime.datetime.now()
    else:
      self._play_pause = False
      now = datetime.datetime.now()
      self._play_start_dt += (now-self._play_pause_dt)
      self._app.mpg123.resume()

  # --- stop playing ----------------------------------------------------------

  def func_stop_play(self,_):
    """ stop playing """

    self.debug("stopping playback")
    self._app.mpg123.stop()
    self._play_start_dt = None

  # --- previous recording   --------------------------------------------------

  def func_prev_recording(self,_):
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

  def func_next_recording(self,_):
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

  def func_exit_playmode(self,_):
    """ start player mode """

    self.debug("stopping player mode")
    self._app.mpg123.stop()
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

  # --- turn radio off   ------------------------------------------------------

  def func_radio_off(self,_):
    """ turn radio off """

    self.debug("turning radio off")
    self._name    = None
    self._channel = -1
    self._app.mpg123.stop()

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
