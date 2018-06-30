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

RECORD_CHUNK = 65536                 # with 128kbs, this should be around 4s


class Radio(Base):
  """ Radio-controller """

  def __init__(self,app):
    """ initialization """

    self._app          = app
    app.register_funcs(self.get_funcs())

    self._active       = True
    self._channel      = -1                 # and no channel
    self._name         = ''                 # and no channel-name
    self.stop_event    = app.stop_event
    self.rec_stop      = None
    self._rec_channel  = None
    self._rec_start_dt = None
    self._rec_show     = True               # toggle: show rec_channel or normal
                                            #         title

  # --- read configuration   --------------------------------------------------

  def read_config(self):
    """ read configuration from config-file """

    # section [GLOBAL]
    self._debug       = self.get_value(self._app.parser,"GLOBAL", "debug","0") == "1"
    default_path        = os.path.join(os.path.expanduser("~"),
                                       "simple-radio.channels")
    self._channel_file  = self.get_value(self._app.parser,"GLOBAL","channel_file",
                                         default_path)

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

  # --- set state   -----------------------------------------------------------

  def set_state(self,active):
    """ set state of object """

    self._active = active

    if active:
      pass
    else:
      self._name    = None
      self._channel = -1

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

  # --- turn radio off   ------------------------------------------------------

  def func_radio_off(self,_):
    """ turn radio off """

    self.debug("turning radio off")
    self._name    = None
    self._channel = -1
    self._app.mpg123.stop()
