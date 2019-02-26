#!/usr/bin/env python
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""library functions to prepare a DUT for lab deployment.

This library will be shared between Autotest and Skylab DUT deployment tools.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import time


def prepare_servo(servo):
    """Prepare servo connected to host for installation steps.

    @param servo  A server.hosts.ServoHost object.
    """
    # Stopping `servod` on the servo host will force `repair()` to
    # restart it.  We want that restart for a few reasons:
    #   + `servod` caches knowledge about the image on the USB stick.
    #     We want to clear the cache to force the USB stick to be
    #     re-imaged unconditionally.
    #   + If there's a problem with servod that verify and repair
    #     can't find, this provides a UI through which `servod` can
    #     be restarted.
    servo.run('stop servod PORT=%d' % servo.servo_port,
              ignore_status=True)
    servo.repair()

    # Don't timeout probing for the host usb device, there could be a bunch
    # of servos probing at the same time on the same servo host.  And
    # since we can't pass None through the xml rpcs, use 0 to indicate None.
    if not servo.get_servo().probe_host_usb_dev(timeout=0):
        raise Exception('No USB stick detected on Servo host')


def install_firmware(host):
    """Install dev-signed firmware after removing write-protect.

    At start, it's assumed that hardware write-protect is disabled,
    the DUT is in dev mode, and the servo's USB stick already has a
    test image installed.

    The firmware is installed by powering on and typing ctrl+U on
    the keyboard in order to boot the the test image from USB.  Once
    the DUT is booted, we run a series of commands to install the
    read-only firmware from the test image.  Then we clear debug
    mode, and shut down.

    @param host   Host instance to use for servo and ssh operations.
    """
    servo = host.servo
    # First power on.  We sleep to allow the firmware plenty of time
    # to display the dev-mode screen; some boards take their time to
    # be ready for the ctrl+U after power on.
    servo.get_power_state_controller().power_off()
    servo.switch_usbkey('dut')
    servo.get_power_state_controller().power_on()
    time.sleep(10)
    # Dev mode screen should be up now:  type ctrl+U and wait for
    # boot from USB to finish.
    servo.ctrl_u()
    if not host.wait_up(timeout=host.USB_BOOT_TIMEOUT):
        raise Exception('DUT failed to boot in dev mode for '
                        'firmware update')
    # Disable software-controlled write-protect for both FPROMs, and
    # install the RO firmware.
    for fprom in ['host', 'ec']:
        host.run('flashrom -p %s --wp-disable' % fprom,
                 ignore_status=True)
    host.run('chromeos-firmwareupdate --mode=factory')
    # Get us out of dev-mode and clear GBB flags.  GBB flags are
    # non-zero because boot from USB was enabled.
    host.run('/usr/share/vboot/bin/set_gbb_flags.sh 0',
             ignore_status=True)
    host.run('crossystem disable_dev_request=1',
             ignore_status=True)
    host.halt()
