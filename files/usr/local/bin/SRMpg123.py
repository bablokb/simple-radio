#!/usr/bin/python
# -----------------------------------------------------------------------------
# Simple radio: implementation of class Mpg123
#
# The class Mpg123 encapsulates the mpg123-process for playing mp3s.
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import threading, subprocess, os, shlex, re, traceback
from threading import Thread

from SRBase import Base

class Mpg123(Base):
  """ mpg123 control-object """

  def __init__(self,app):
    """ initialization """

    self._app       = app
    self._queue     = app.display.queue
    self._process   = None
    self._icy_event = None

  # --- read configuration   --------------------------------------------------

  def read_config(self):
    """ read configuration from config-file """

    # section [GLOBAL]
    self._debug  = self.get_value(self._app.parser,"GLOBAL", "debug","0") == "1"
    self._mpg123_opts = self.get_value(self._app.parser,"GLOBAL",
                                       "mpg123_opts","-b 1024")
    # TODO: remove again, we need this during transition
    self._cols        = int(self.get_value(self._app.parser,"DISPLAY", "cols",16))
    self._rows        = int(self.get_value(self._app.parser,"DISPLAY", "rows",2))

  # --- active-state (return true if playing)   --------------------------------

  def is_active(self):
    """ return active (playing) state """

    return not self._process is None and not self._process.poll() is None

  # --- start to play music   ------------------------------------------------

  def start(self,name,radio_mode):
    """ spawn new mpg123 process """

    args = ["mpg123"]
    opts = shlex.split(self._mpg123_opts)
    args += opts
    if name.endswith(".m3u"):
      args += ["-@",name]
    else:
      args += [name]

    self.debug("with args %r" % (args,))
    self._process = subprocess.Popen(args,bufsize=1,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
    if radio_mode:
      self._icy_event = threading.Event()
      self._icy_thread = threading.Thread(target=self.read_icy_meta)
      self._icy_thread.start()
    else:
      self._icy_event = None

  # --- pause playing   -------------------------------------------------------

  def pause(self):
    """ pause playing """

    self.debug("pausing playback")
    if self.is_active():
      self._process.send_signal(signal.SIGSTOP)

  # --- continue playing   ----------------------------------------------------

  def cont(self):
    """ continue playing """

    self.debug("continuing playback")
    if self.is_active():
      self._process.send_signal(signal.SIGCONT)

  # --- stop player   ---------------------------------------------------------

  def stop(self):
    """ stop current player """

    if self._process:
      self.debug("stopping player ...")
      try:
        self._process.terminate()
      except:
        pass
      self._process = None
      if self._icy_event:
        self._icy_event.set()
        self._icy_thread.join()
        self._icy_event = None
      self.debug("... done stopping player")

  # --- read ICY-meta-tags during playback   ----------------------------------

  def read_icy_meta(self):
    """ read ICY-meta-tags of current playback """

    self.debug("starting read_icy_meta")

    regex = re.compile(r".*ICY-META.*?'(.*)';$")
    try:
      while True:
        if self._icy_event.wait(0.01):
          self.debug("terminating on stop request")
          break
        try:
          data = self._process.stdout.readline()
          data = data.decode('utf-8')
        except:
          self.debug("could not decode: '%s'" % data)
          self.debug("ignoring data")
          continue
        if data == '' and self._process.poll() is not None:
          # this is an error condition, bail out
          self.debug("undefined error condition")
          return
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

          # TODO: move to display
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
            self._queue.put(line[:split])
            line = rest
            self.debug("text left: %s" % line)
          if len(line):
            self._queue.put(line)
          # send separator
          self._queue.put("%s%s" % (((self._cols-6)/2)*' ',6*'*'))

    except:
      # typically an IO-exception due to closing of stdout
      if self._debug:
        print traceback.format_exc()
      pass

    # clear all pending lines
    self.debug("clearing queued lines ...")
    try:
      count = 0
      while not self._queue.empty():
        count += 1
        self.debug("  ... %d" % count)
        self._queue.get_nowait()
    except:
      if self._debug:
        print traceback.format_exc()
      pass
    self.debug("... and clearing lines on the display")
    for i in range(self._rows-1):
      self._queue.put(" ")

