Simple Radio
============

This project implements a simple internet-radio using

  - a Raspberry Pi (or a similar SBC)
  - a TTP229-based keypad
  - a LCD-display (typically with 2-4 rows and 16-20 columns)

![](images/simple-radio.jpg "Pi-Zero with TTP229-keypad and 1602-LCD")

Basic features of the implementation:

  - select predefined radio-stations using the keypad
  - display date and time and channel name on the display
  - display ICY-META data on the display
  - record a radio-channel (either unattended or on request)
  - playback recordings


Hardware prerequisites
----------------------

This project assumes that you have a basic installation of Raspbian
(or a similar OS, e.g. Armbian on other platforms). You should have
successfully configured sound. You should also know how to connect
a LCD display using the I2C-interface and the keypad to your Pi.
For the LCD you will find many tutorials on the net, for the keypad
you should head over to my
[pi-ttp229-keypad project](https://github.com/bablokb/pi-ttp229-keypad "keypad-project").

Note: using only the recorder-part of the project does not require
the display and the keypad - even the configuration of the sound-system
is not necessary as long as you use a different system for playback. So
the recorder can be operated on a pure headless system.

Installation
------------

Use the following commands to install the software and all prerequisites:

    git clone https://github.com/bablokb/pi-ttp229-keypad.git
    cd pi-ttp229-keypad
    sudo tools/install
    cd ..

    git clone https://github.com/bablokb/simple-radio.git
    cd simple-radio
    sudo tools/install pi

The firt set of commands installs the code for the keypad, the second set
installs the code of this project. If your standard user is not `pi`,
you should pass a different name to the install command.

Both installations will ask you to configure the software using the files
`/etc/ttp229-keypad.conf` and `/etc/simple-radio.conf` respectively.


Configuration
-------------

The config-file of this project has a number of sections. The `[GLOBAL]`
section configures some basic properties. The section `[DISPLAY]` lists
the attributes (rows and columns) of your display. Not every display has
all the characters at the correct code-points, you can use to translate
characters to the correct codepoint with the `trans`-variable:

    trans:  äöüßÄÖÜíáéè, e1,ef,f5,e2,e1,ef,f5,69,61,65,65

This variable holds a comma-separated list of strings. The first string
contains all special characters, the rest are the relevant replacement
code-points. For every character in the first string you need a
replacement point. The installation provides a little script `show_charset.py`,
this will display all code-points:

    show_charset.py 0 1 2 3

will display chars 0-15 and so on.

The section `[RECORD]` defines the default target-directory for recordings
and the default duration. Both values can be overriden on the commandline.
The default duration prevents that your SD-card is filled with a very
long recording in case you forget to stop the recording.

The `[KEYS]`-section defines the mapping of the 16 keys to predefined
commands. The example maps the first 12 keys to `switch_channel`, i.e.
key 5 will switch to channel number 5 (see below).

The `[PLAYER]`-section holds the key-mapping in player-mode.

The configuration file has a list of all available commands you can match
to the keys.


Channel-file
------------

During startup, the program loads a simple list of radio-channels from
the file defined in variable `[GLOBAL] -> channel_file`. The default filename
is `/home/pi/simple-radio.channels` (replace `pi` with the name of your user
you passed to the install-command). The file should contain lines in
the format

    name@url

e.g.

    Bayern 3@http://br-br3-live.cast.addradio.de/br/br3/live/mp3/128/stream.mp3

Note the blank in the name-part (this is supported), but `name` should not
contain a `@`. The maximum length of `name` is 10 on a display with 16 columns
and 14 on a display with 20 columns.

The mapping to channel numbers is straightforward: the first line defines
channel 1, the second line channel 2 and so on.

The install-script copies a sample channel file from
`examples/simple-radio.channels` to the home-directory of the user passed
to the install-command. The sample channels-file contains a number
of public radio channels in Germany. Note that the URLs are not
stable and tend to change over time.
