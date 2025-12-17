# Exercise for Real-Time Operating Systems Design and Implementation 25/26
In order to use the setup you will need to configure your system in the following way:

1. Install the required system packages and configure your system accordingly
2. Run the `local_setup.sh` script to install and setup the development environment
3. To build the sample project, we use the provided `idf.py` scripts:
    1. To activate the `idf.py` script, run `. ./esp/esp-idf/export.sh` from the root of the repository
    2. To build the project, run `idf.py build`
    3. To flash the firmware to a connected Watchy, run `idf.py flash`
    4. To display serial output on your console, run `idf.py monitor`

If you use Linux, see the [Setup Linux](#setup-linux) section below for required packages and system configurations.

If you use macOS, see the [Setup macOS](#setup-macOS) section below for required packages.

### Setup Linux

- Make sure you have the [required dependencies](https://docs.espressif.com/projects/esp-idf/en/v5.5.1/esp32/get-started/linux-macos-setup.html#for-linux-users) installed. A starting point of debian packages would be
  `git wget flex bison gperf python3 python3-pip python3-venv cmake ninja-build ccache libffi-dev libssl-dev dfu-util libusb-1.0-0`
- In order to flash the project, your user needs permissions to access the device. Consider adding your user to the dialout group: `sudo usermod -a -G dialout $USER`

### Setup macOS

- Make sure the [required dependencies](https://docs.espressif.com/projects/esp-idf/en/v5.5.1/esp32/get-started/linux-macos-setup.html#for-macos-users) are installed. If you use HomeBrew, they can be installed with:
  `brew install cmake ninja dfu-util`
- You need a Python 3 interpreter, for example, you can use the bundled Python 3.9 interpreter (on macOS Sonoma). If your bundled Python version is Python 2, [install a Python 3 interpreter](https://docs.espressif.com/projects/esp-idf/en/v5.5.1/esp32/get-started/linux-macos-setup.html#installing-python-3), for example with HomeBrew.
