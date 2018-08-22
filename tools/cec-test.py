#!/usr/bin/python
#encoding: utf-8
# -----------------------------------------------------------------------------
# CEC test-programm. Interactive "shell" to test various CEC-functions.
#
# Part of this code is copied from the libcec-source taken from
# libcec/src/pyCecClient/pyCecClient.py
#
#libCEC(R) is Copyright (C) 2011-2015 Pulse-Eight Limited.  All rights reserved.
#libCEC(R) is a original work, containing original code.
#libCEC(R) is a trademark of Pulse-Eight Limited.
# License: GPL2 (original libcec-license)
#
# Author: Bernhard Bablok
# License: GPL3
#
# Website: https://github.com/bablokb/simple-radio
#
# -----------------------------------------------------------------------------

import cec, readline

class CecController:

  # --- constructor   --------------------------------------------------------
  
  def __init__(self):
    self.log_level = cec.CEC_LOG_WARNING
    self.cecconfig = cec.libcec_configuration()
    self.cecconfig.strDeviceName   = "simple-radio"
    self.cecconfig.bActivateSource = 0
    self.cecconfig.deviceTypes.Add(cec.CEC_DEVICE_TYPE_TUNER)
    self.cecconfig.clientVersion = cec.LIBCEC_VERSION_CURRENT

    self.cecconfig.SetLogCallback(self.process_logmessage)
    self.cecconfig.SetKeyPressCallback(self.process_key)
    self.cecconfig.SetCommandCallback(self.process_command)

    self.controller = cec.ICECAdapter.Create(self.cecconfig)
    print("libCEC version " +
          self.controller.VersionToString(self.cecconfig.serverVersion) +
          " loaded: " + self.controller.GetLibInfo())

    # search for adapters
    self.com_port = self.get_com_port()

    if self.com_port == None:
      raise EnvironmentError((1,"Kein CEC-Adapter gefunden"))
    
    if not self.controller.Open(self.com_port):
      raise EnvironmentError((2,"konnte CEC-Adapter nicht öffnen"))

  # --- process key presses   ------------------------------------------------
  
  def process_key(self, key, duration):
    print("Taste: " + str(key))
    return 0

  # --- process commands   ---------------------------------------------------
  
  def process_command(self, cmd):
    print("Kommando: " + cmd)
    return 0

  # --- process log-messages   ------------------------------------------------
  
  def process_logmessage(self, level, time, message):
    if level > self.log_level:
      return 0

    if level == cec.CEC_LOG_ERROR:
      levelstr = "ERROR:   "
    elif level == cec.CEC_LOG_WARNING:
      levelstr = "WARNING: "
    elif level == cec.CEC_LOG_NOTICE:
      levelstr = "NOTICE:  "
    elif level == cec.CEC_LOG_TRAFFIC:
      levelstr = "TRAFFIC: "
    elif level == cec.CEC_LOG_DEBUG:
      levelstr = "DEBUG:   "

    print(levelstr + "[" + str(time) + "]     " + message)
    return 0

  # --- return com port path of adapter   -------------------------------------

  def get_com_port(self):
    for adapter in self.controller.DetectAdapters():
      print("CEC Adapter:")
      print("Port:     " + adapter.strComName)
      print("vendor:   " + hex(adapter.iVendorId))
      print("Produkt:  " + hex(adapter.iProductId))
      return adapter.strComName

    print("Keinen Adapter gefunden")
    return None

  # --- display the addresses controlled by libCEC   -------------------------
  
  def print_addresses(self):
    addresses = self.controller.GetLogicalAddresses()
    strOut = "Addresses controlled by libCEC: "
    x = 0
    notFirst = False
    while x < 15:
      if addresses.IsSet(x):
        if notFirst:
          strOut += ", "
        strOut += self.controller.LogicalAddressToString(x)
        if self.controller.IsActiveSource(x):
          strOut += " (*)"
        notFirst = True
      x += 1
    print(strOut)

  # --- send an active source message   --------------------------------------
  
  def set_active(self):
    self.controller.SetActiveSource()

  # --- send a standby command   ---------------------------------------------
  
  def send_standby(self):
    self.controller.StandbyDevices(cec.CECDEVICE_BROADCAST)

  # --- send mute command   --------------------------------------------------
  
  def toggle_mute(self):
    self.controller.AudioToggleMute()

  # --- increase volume   ----------------------------------------------------
  
  def volume_up(self):
    self.controller.VolumeUp()

  # --- decrease volume   ----------------------------------------------------
  
  def volume_down(self):
    self.controller.VolumeDown()

  # --- send a custom command   ----------------------------------------------
  
  def send_command(self, data):
    cmd = self.controller.CommandFromString(data)
    print("übertrage " + data)
    if self.controller.Transmit(cmd):
      print("Kommando gesendet")
    else:
      print("Kommando konnte nicht gesendet werden")

  # --- scan the bus   -------------------------------------------------------
  
  def scan_bus(self):
    print("Scanne den CEC bus ...")
    strLog = "CEC bus Informationen:\n\n"
    addresses = self.controller.GetActiveDevices()
    activeSource = self.controller.GetActiveSource()
    x = 0
    while x < 15:
      if addresses.IsSet(x):
        vendorId        = self.controller.GetDeviceVendorId(x)
        physicalAddress = self.controller.GetDevicePhysicalAddress(x)
        active          = self.controller.IsActiveSource(x)
        cecVersion      = self.controller.GetDeviceCecVersion(x)
        power           = self.controller.GetDevicePowerStatus(x)
        osdName         = self.controller.GetDeviceOSDName(x)
        strLog += "Device #" + str(x) +": " + self.controller.LogicalAddressToString(x)  + "\n"
        strLog += "Adresse:       " + str(physicalAddress) + "\n"
        strLog += "Active Source: " + str(active) + "\n"
        strLog += "Vendor:        " + self.controller.VendorIdToString(vendorId) + "\n"
        strLog += "CEC Version:   " + self.controller.CecVersionToString(cecVersion) + "\n"
        strLog += "OSD Name:      " + osdName + "\n"
        strLog += "Power Status:  " + self.controller.PowerStatusToString(power) + "\n\n\n"
      x += 1
    print(strLog)

  # --- run and process commands   --------------------------------------------
  
  def run(self):
    while True:
      command = raw_input("Kommando: ").lower()
      if command == 'q' or command == 'quit':
        print('Beende das Programm...')
        return
      elif command == 'info':
        self.print_addresses()
      elif command == 'as' or command == 'activesource':
        self.set_active()
      elif command == 'standby':
        self.send_standby()
      elif command == 'scan':
        self.scan_bus()
      elif command == 'mute':
        self.toggle_mute()
      elif command == 'volup':
        self.volume_up()
      elif command == 'voldown':
        self.volume_down()
      elif command[:2] == 'tx':
        self.send_command(command[3:])

if __name__ == '__main__':
  # initialise main object
  controller = CecController()
  controller.run()
