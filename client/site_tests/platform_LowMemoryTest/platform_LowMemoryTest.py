# Copyright (c) 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import re
import time

from autotest_lib.client.bin import test
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import chrome
from autotest_lib.client.cros import cros_logging

class MemoryKillsMonitor:
    """A util class for reading kill events."""

    _LOG_FILE = '/var/log/chrome/chrome'
    _PATTERN_DISCARD = re.compile(
        'tab_manager_delegate_chromeos.*:(\d+) Killed tab')
    _PATTERN_OOM = re.compile('Tab OOM-Killed Memory details:')

    def __init__(self):
        self._log_reader = cros_logging.ContinuousLogReader(self._LOG_FILE)

    def check_event(self):
        """Returns the first monitored kill event or empty string"""
        for line in self._log_reader.read_all_logs():
            matched = self._PATTERN_DISCARD.search(line)
            if matched:
                logging.info('Matched line %s', line)
                return 'LOW_MEMORY_KILL_TAB'
            matched = self._PATTERN_OOM.search(line)
            if matched:
                logging.info('Matched line %s', line)
                return 'OOM_KILL'
        return ''


def create_pages_and_check_oom(create_page_func, bindir):
    """Common code to create pages and to check OOM.

    Args:
        create_page_func: function to create page.
        bindir: path to the test directory.
    Returns:
        Dictionary of test results.
    """
    # 1 for initial tab opened
    n_tabs = 1

    kills_monitor = MemoryKillsMonitor()
    last_event = ''
    # Open tabs until a tab discard notification or OOM arrives.
    with chrome.Chrome(init_network_controller=True) as cr:
        cr.browser.platform.SetHTTPServerDirectories(bindir)
        while last_event == '':
            create_page_func(cr, bindir)
            time.sleep(3)
            n_tabs += 1
            last_event = kills_monitor.check_event()

    # Test is successful if at least one Chrome tab is killed by tab
    # discarder before kernel OOM killer invoked.
    if last_event == 'OOM_KILL':
        raise error.TestFail('OOM Kill happends before a tab is killed')

    return {'NumberOfTabsAtFirstDiscard': n_tabs}


def create_alloc_page(cr, size_mb, bindir):
    """The program in alloc.html allocates a large array with random data.

    Args:
        cr: chrome wrapper.
        size_mb: size of the allocated javascript array in the page.
        bindir: path to the test directory.
    """
    url = cr.browser.platform.http_server.UrlOf(
        os.path.join(bindir, 'alloc.html'))
    url += '?alloc=' + str(size_mb)
    tab = cr.browser.tabs.New()
    tab.Navigate(url)
    tab.WaitForDocumentReadyStateToBeComplete()
    tab.WaitForJavaScriptCondition(
        "document.hasOwnProperty('out') == true", timeout=60)


def create_random_page(cr, bindir):
    """Creates pages with certain size of random data.

    Args:
        cr: chrome wrapper.
        bindir: path to the test directory.
    """
    ALLOC_MB_PER_PAGE_DEFAULT = 800
    ALLOC_MB_PER_PAGE_SUB_2GB = 400
    GB_TO_BYTE = 1024 * 1024 * 1024
    KB_TO_BYTE = 1024

    alloc_mb_per_page = ALLOC_MB_PER_PAGE_DEFAULT
    # Allocate less memory per page for devices with 2GB or less memory.
    if utils.memtotal() * KB_TO_BYTE < 2 * GB_TO_BYTE:
        alloc_mb_per_page = ALLOC_MB_PER_PAGE_SUB_2GB

    create_alloc_page(cr, alloc_mb_per_page, bindir)


def random_pages(bindir):
    """Creates pages with random content and checks OOM.

    Args:
        bindir: path to the test directory.
    """
    return create_pages_and_check_oom(create_random_page, bindir)


class platform_LowMemoryTest(test.test):
    """Memory pressure test."""
    version = 1

    def run_once(self, flavor='random'):
        """Runs the test once."""
        if flavor == 'random':
            perf_results = random_pages(self.bindir)

        self.write_perf_keyval(perf_results)
        for result_key in perf_results:
            self.output_perf_value(description=result_key,
                                   value=perf_results[result_key],
                                   higher_is_better=True)

