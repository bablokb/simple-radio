#!/usr/bin/python3
# -----------------------------------------------------------------------------
# This program prints the available charset to the display
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import sys, time, traceback

I2C_PORT   = 1
SLEEP_TIME = 5
COLS       = 20
ROWS       = 4

try:
  import lcddriver
  lcd = lcddriver.lcd(port=I2C_PORT)
  simulate = False
except:
  print traceback.format_exc()
  simulate = True

if COLS == 20:
  header = "    0123456789012345"
else:  
  header = "0123456789012345"

for part in sys.argv[1:]:
  part = int(part)
  if COLS == 20:
    line = "%3d:" % (part*16)
  else:
    line = ""
  for nr in range(part*16,part*16+16):
    line += (chr(nr))

  # output header and content
  if simulate:
    print header
    print line
  else:
    lcd.lcd_display_string(header,1)
    lcd.lcd_display_string(line,2)

  # and sleep
  time.sleep(SLEEP_TIME)
