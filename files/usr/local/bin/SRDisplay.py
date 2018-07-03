#!/usr/bin/python
# -----------------------------------------------------------------------------
# Simple radio: implementation of class Display
#
# The class Display controls a 1602 or 2004 LCD-display
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import threading, os
from threading import Thread
import Queue, collections

try:
  import lcddriver
  have_lcd = True
except ImportError:
  print("[WARNING] could not import lcddriver")
  have_lcd = False

from SRBase import Base

class Display(Thread,Base):
  """ Display-controller """

  def __init__(self,app):
    """ initialization """
    super(Display,self).__init__(name="Display")

    self._app              = app
    self._content_queue    = Queue.Queue()         # for split content data
    self._content_provider = None                  # content provider
    self.read_config()

  # --- read configuration   --------------------------------------------------

  def read_config(self):
    """ read configuration from config-file """

    # section [GLOBAL]
    self._debug  = self.get_value(self._app.parser,"GLOBAL", "debug","0") == "1"
    self._i2c    = int(self.get_value(self._app.parser,"GLOBAL","i2c",0))

    # section [DISPLAY]
    have_disp         = (self.get_value(self._app.parser,
                                        "DISPLAY", "display","0") == "1")
    self.have_disp    = have_lcd and have_disp
    self._rows        = int(self.get_value(self._app.parser,"DISPLAY", "rows",2))
    self._cols        = int(self.get_value(self._app.parser,"DISPLAY", "cols",16))
    self._scroll_time = int(self.get_value(self._app.parser,"DISPLAY", "scroll",3))

    rule              = self.get_value(self._app.parser,"DISPLAY","trans",None)
    self._build_map(rule)

  # --- build translation map for display   -----------------------------------

  def _build_map(self,rule):
    """ build the translation map """

    if rule:
      rule            = rule.split(",")
      rule[0]         = rule[0].decode('UTF-8')
      self._transmap = {}
      for i in range(len(rule[0])):
        self._transmap[rule[0][i]] = int(rule[i+1],16)
    else:
      self._transmap  = None

  # --- set content-provider   ------------------------------------------------

  def set_content_provider(self,provider):
    """ set content-provider """

    self.debug("set content-provider")
    self._content_provider = provider

  # --- initialize display   -------------------------------------------------

  def init(self):
    """ initialize display """

    # initialize data structures
    self._content_deque   = collections.deque(maxlen=self._rows-1)
    self._fmt_line        = u"{0:%d.%ds}" % (self._cols,self._cols)

    # initialize hardware
    try:
      self._lcd = lcddriver.lcd(port=self._i2c,tmap=self._transmap)
    except NameError:
      self.debug("no display detected")
      self.have_disp = False
    title = self._content_provider.get_title()
    self._update_display(self._format_title(*title),[],True)

  # --- clear display   -----------------------------------------------------

  def clear(self):
    """ clear the display """
    if self.have_disp:
      self._lcd.lcd_clear()

  # --- clear current content   ---------------------------------------------

  def clear_content(self):
    """ clear current content """

    try:
      count = 0
      while not self._content_queue.empty():
        count += 1
        self.debug("  ... %d" % count)
        self._content_queue.get_nowait()
    except:
      if self._debug:
        print traceback.format_exc()
      pass
    self.debug("... and clearing lines on the display")
    for i in range(self._rows-1):
      self._content_queue.put(" ")

  # --- split content to fit to the display   -------------------------------

  def _split_content(self,lines):
    """ split content into chunks """

    for line in lines:
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
        self._content_queue.put(line[:split])
        line = rest
        self.debug("text left: %s" % line)
      if len(line):
        self._content_queue.put(line)

  # --- pull the next content from the queue to the display-deque   ---------

  def _next_content(self):
    # poll queue for data and append to deque
    try:
      for  i in range(self._rows-1):
        line = self._content_queue.get_nowait()
        self.debug("update_display: line: %s" % line)
        self._content_deque.append(line)
    except Queue.Empty:
      self._content_deque.append("")
    except:
      if self._debug:
        print traceback.format_exc()

  # --- write to the display   ----------------------------------------------

  def _update_display(self,title,lines,clear=False):
    """ write to the display """

    # clear screen in simulation-mode (unless debugging)
    if clear:
      if self.have_disp:
        pass
      else:
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

  # --- format title   -------------------------------------------------------

  def _format_title(self,left,right):
    """ format title """

    len_left  = len(left)
    len_right = len(right)
    pad       = self._cols - 1 - len_left - len_right

    if pad < 0:
      # truncate left string
      return left[:len_left+pad] + ' ' + right
    elif pad == 0:
      # perfect fit
      return left + ' ' + right
    else:
      # pad between left and right
      return left + ' ' + pad*' ' + right

  # --- display-controller thread    -----------------------------------------

  def run(self):
    """ display-controller-thread """

    self.debug("starting update_display")

    while True:
      if self._content_provider:
        title   = self._content_provider.get_title()
        content = self._content_provider.get_content()
        if content:
          self._split_content(content)                 # split and push
      else:
        title = ("","")
      self._next_content()                             # pop lines to deque
      self._update_display(self._format_title(*title),self._content_deque)

      # sleep
      if self._app.stop_event.wait(self._scroll_time):
        self.debug("terminating update_display on stop request")
        if self.have_disp:
          self._lcd.lcd_clear()
          self._lcd.lcd_backlight('OFF')
        return
