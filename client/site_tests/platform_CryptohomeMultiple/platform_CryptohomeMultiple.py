# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import cryptohome

class platform_CryptohomeMultiple(test.test):
    version = 1
    chome = None

    def test_mount_single(self):
        """
        Tests mounting a single not-already-existing cryptohome. Ensures that
        the infrastructure for multiple mounts is present and active.
        """
        user = utils.random_username()
        if not self.chome.mount(user, 'test', create=True):
            raise error.TestFail('Mount failed for %s' % user)
        self.chome.require_mounted(user)
        if not self.chome.unmount(user):
            raise error.TestFail('Unmount failed for %s' % user)

    def run_once(self):
        self.chome = cryptohome.Cryptohome()
        self.test_mount_single()
