# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.bin import test
from autotest_lib.client.cros import cryptohome
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import chrome


class login_GaiaLogin(test.test):
    """Sign into production gaia using Telemetry."""
    version = 1


    _USERNAME = 'powerloadtest@gmail.com'
    # TODO(achuith): Get rid of this when crbug.com/358427 is fixed.
    _USERNAME_DISPLAY = 'power.loadtest@gmail.com'
    _PASSWORD = 'power_LoadTest2'

    def run_once(self):
        with chrome.Chrome(gaia_login=True, username=self._USERNAME,
                                            password=self._PASSWORD) as cr:
            if not cryptohome.is_vault_mounted(user=self._USERNAME):
                raise error.TestFail('Expected to find a mounted vault for %s'
                                     % self._USERNAME)
            tab = cr.browser.tabs.New()
            # TODO(achuith): Use a better signal of being logged in, instead of
            # parsing accounts.google.com.
            tab.Navigate('http://accounts.google.com')
            tab.WaitForDocumentReadyStateToBeComplete()
            found = tab.EvaluateJavaScript('''
                    var found = 0;
                    var divs = document.getElementsByTagName('div');
                    for (var i = 0; i < divs.length; i++) {
                        if (divs[i].textContent.search('%s')) {
                            found = 1;
                            break;
                        }
                    }
                    found;
            ''' % self._USERNAME_DISPLAY)
            if not found:
                raise error.TestFail('No references to %s on accounts page.'
                                     % self._USERNAME_DISPLAY)
            tab.Close()
