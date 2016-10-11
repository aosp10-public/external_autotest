# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from autotest_lib.client.common_lib import error
from autotest_lib.client.cros.enterprise import enterprise_policy_base


class policy_RestoreOnStartupURLs(enterprise_policy_base.EnterprisePolicyTest):
    """Test effect of RestoreOnStartupURLs policy on Chrome OS behavior.

    This test verifies the behavior of Chrome OS for a range of valid values
    in the RestoreOnStartupURLs user policy. It also exercises the dependent
    user policy RestoreOnStartup, which must be set to 4 to utilize the
    specified startup URLs, and to None to when no URLs are specified.

    The combination of policy values are covered by three test cases named:
    NotSet_NoTabs, SingleUrl_1Tab, and MultipleUrls_3Tabs.
    - Case NotSet_NoTabs opens no tabs. This is the default behavior for
      un-managed user and guest user sessions.
    - Case SingleUrl_1Tab opens a single tab to chrome://settings.
    - Case MultipleUrls_3Tabs opens 3 tabs, in order, to the following pages:
      'chrome://policy', 'chrome://settings', and 'chrome://histograms'

    """
    version = 1

    POLICY_NAME = 'RestoreOnStartupURLs'
    URLS1_DATA = ['chrome://settings']
    URLS3_DATA = ['chrome://policy', 'chrome://settings',
                  'chrome://histograms']
    NEWTAB_URLS = ['chrome://newtab',
                   'https://www.google.com/_/chrome/newtab?espv=2&ie=UTF-8']

    TEST_CASES = {
        'NotSet_NoTabs': None,
        'SingleUrl_1Tab': URLS1_DATA,
        'MultipleUrls_3Tabs': URLS3_DATA
    }

    def _test_startup_urls(self, policy_value, policies_dict):
        """Verify CrOS enforces RestoreOnStartupURLs policy value.

        When RestoreOnStartupURLs policy is set to one or more URLs, check
        that a tab is opened to each URL. When set to None, check that no tab
        is opened.

        @param policy_value: policy value expected on chrome://policy page.
        @param policies_dict: policy dict data to send to the fake DM server.

        """
        logging.info('Running _test_StartupURLs(%s, %s)',
                     policy_value, policies_dict)
        self.setup_case(self.POLICY_NAME, policy_value, policies_dict)

        # Get list of open tab urls from browser; Convert unicode to text;
        # Strip any trailing '/' character reported by devtools.
        tab_urls = [tab.url.encode('utf8').rstrip('/')
                    for tab in reversed(self.cr.browser.tabs)]
        tab_urls_value = ','.join(tab_urls)

        # Telemetry always opens a 'newtab' tab if no startup tabs are opened.
        # If the only open tab is 'newtab', or a tab with the termporary url
        # www.google.com/_/chrome/newtab..., then set tab URLs to None.
        if tab_urls_value in self.NEWTAB_URLS:
            tab_urls_value = None

        # Compare open tabs with expected tabs by |policy_value|.
        if tab_urls_value != policy_value:
            raise error.TestFail('Unexpected tabs: %s '
                                 '(expected: %s)' %
                                 (tab_urls_value, policy_value))

    def run_test_case(self, case):
        """Setup and run the test configured for the specified test case.

        Set the expected |policy_value| string and |policies_dict| data based
        on the test |case|. Set RestoreOnStartup=4 when there is 1 or more
        startup urls given. Otherwise, set to None.

        @param case: Name of the test case to run.

        """
        if self.TEST_CASES[case] is None:
            policy_value = None
            policies_dict = {'RestoreOnStartup': None}
        else:
            policy_value = ','.join(self.TEST_CASES[case])
            policies_dict = {'RestoreOnStartup': 4}
        policy_dict = {self.POLICY_NAME: self.TEST_CASES[case]}
        policies_dict.update(policy_dict)
        self._test_startup_urls(policy_value, policies_dict)
