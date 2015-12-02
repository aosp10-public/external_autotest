# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.network import xmlrpc_datatypes
from autotest_lib.server.cros.network import hostap_config
from autotest_lib.server.cros.network import wifi_cell_test_base


class network_WiFi_DisconnectClearsIP(wifi_cell_test_base.WiFiCellTestBase):
    """Check that we remove our IP after disconnection from a WiFi network."""

    version = 1


    def run_once(self):
        """Test body."""
        ap_config = hostap_config.HostapConfig(
                frequency=2412,
                mode=hostap_config.HostapConfig.MODE_11G)
        client_config = xmlrpc_datatypes.AssociationParameters()
        self.context.configure(ap_config)
        client_config.ssid = self.context.router.get_ssid()
        self.context.assert_connect_wifi(client_config)
        if self.context.client.wifi_ip is None:
            raise error.TestFail('After connecting, we should have an IP.')

        self.context.assert_ping_from_dut()
        self.context.client.shill.disconnect(self.context.router.get_ssid())
        if self.context.client.wifi_ip is not None:
            raise error.TestFail('After disconnecting, we should '
                                 'not have an IP.')
