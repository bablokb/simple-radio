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

from SRBase import Base

class Display(Thread,Base):
  """ Display-controller """

  def __init__(self,app):
    """ initialization """
    super(Display,self).__init__(name="Display")

    self.queue = Queue.Queue()
