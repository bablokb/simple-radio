Simple Radio
============

This project implements a simple internet-radio using

  - a Raspberry Pi (or a similar SBC)
  - a TTP229-based keypad
  - a LCD-display (typically with 2-4 rows and 16-20 columns)

Basic features of the implementation:

  - select predefined radio-stations using the keypad
  - display date and time and channel name on the display
  - display ICY-META data on the display


Hardware prerequisites
----------------------

This project assumes that you have a basic installation of Raspbian
(or a similar OS, e.g. Armbian on other platforms). You should have
successfully configured sound. You should also know how to connect
a LCD display using the I2C-interface and the keypad to your Pi.
For the LCD you will find many tutorials on the net, for the keypad
you should head over to my
[pi-ttp229-keypad project](https://github.com/bablokb/pi-ttp229-keypad "keypad-project").


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
the attributes (rows and columns) of your display. Most importantly,
the `[KEYS]`-section defines the mapping of the 16 keys to predefined
commands. The example maps the first 12 keys to `switch_channel`, i.e.
key 5 will switch to channel number 5 (see below).


Channel-file
------------

During startup, the program loads a simple list of radio-channels from
the file defined in variable `[GLOBAL] -> channel_file`. The default filename
is `/home/pi/simple-radio.channels`. The file should contain lines in
the format

    name@url

e.g.

    Bayern 3@http://br-br3-live.cast.addradio.de/br/br3/live/mp3/128/stream.mp3

Note the blank in the name-part (this is supported), but `name` should not
contain a `@`. The maximum length of `name` is 10 on a display with 16 columns
and 14 on a display with 20 columns.

The mapping to channel numbers is straightforward: the first line defines
channel 1, the second line channel 2 and so on.

You can find a sample channel file in `examples/simple-radio.channels` with
a number of public radio channels in Germany. Note that the URLs are not
stable and tend to change over time.
