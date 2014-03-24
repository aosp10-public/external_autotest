# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import logging
import random
import string
import time

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.network import interface
from autotest_lib.client.common_lib.cros.network import netblock
from autotest_lib.server import site_linux_system
from autotest_lib.server.cros import wifi_test_utils
from autotest_lib.server.cros.network import hostap_config


StationInstance = collections.namedtuple('StationInstance',
                                         ['ssid', 'interface', 'dev_type'])


class LinuxRouter(site_linux_system.LinuxSystem):
    """Linux/mac80211-style WiFi Router support for WiFiTest class.

    This class implements test methods/steps that communicate with a
    router implemented with Linux/mac80211.  The router must
    be pre-configured to enable ssh access and have a mac80211-based
    wireless device.  We also assume hostapd 0.7.x and iw are present
    and any necessary modules are pre-loaded.

    """

    KNOWN_TEST_PREFIX = 'network_WiFi'
    STARTUP_POLLING_INTERVAL_SECONDS = 0.5
    STARTUP_TIMEOUT_SECONDS = 10
    SUFFIX_LETTERS = string.ascii_lowercase + string.digits
    SUBNET_PREFIX_OCTETS = (192, 168)

    HOSTAPD_CONF_FILE_PATTERN = '/tmp/hostapd-test-%s.conf'
    HOSTAPD_LOG_FILE_PATTERN = '/tmp/hostapd-test-%s.log'
    HOSTAPD_PID_FILE_PATTERN = '/tmp/hostapd-test-%s.pid'
    HOSTAPD_CONTROL_INTERFACE_PATTERN = '/tmp/hostapd-test-%s.ctrl'
    HOSTAPD_DRIVER_NAME = 'nl80211'

    STATION_CONF_FILE_PATTERN = '/tmp/wpa-supplicant-test-%s.conf'
    STATION_LOG_FILE_PATTERN = '/tmp/wpa-supplicant-test-%s.log'
    STATION_PID_FILE_PATTERN = '/tmp/wpa-supplicant-test-%s.pid'

    MGMT_FRAME_SENDER_LOG_FILE = '/tmp/send_management_frame-test.log'

    def get_capabilities(self):
        """@return iterable object of AP capabilities for this system."""
        caps = set([self.CAPABILITY_IBSS])
        try:
            self.cmd_send_management_frame = wifi_test_utils.must_be_installed(
                    self.host, '/usr/bin/send_management_frame')
            caps.add(self.CAPABILITY_SEND_MANAGEMENT_FRAME)
        except error.TestFail:
            pass
        return super(LinuxRouter, self).get_capabilities().union(caps)


    @property
    def router(self):
        """Deprecated.  Use self.host instead.

        @return Host object representing the remote router.

        """
        return self.host


    @property
    def wifi_ip(self):
        """Simple accessor for the WiFi IP when there is only one AP.

        @return string IP of WiFi interface.

        """
        if len(self.local_servers) != 1:
            raise error.TestError('Could not pick a WiFi IP to return.')

        return self.get_wifi_ip(0)


    def __init__(self, host, test_name):
        """Build a LinuxRouter.

        @param host Host object representing the remote machine.
        @param test_name string name of this test.  Used in SSID creation.

        """
        super(LinuxRouter, self).__init__(host, 'router')

        self.cmd_dhcpd = '/usr/sbin/dhcpd'
        self.cmd_hostapd = wifi_test_utils.must_be_installed(
                host, '/usr/sbin/hostapd')
        self.cmd_hostapd_cli = wifi_test_utils.must_be_installed(
                host, '/usr/sbin/hostapd_cli')
        self.cmd_wpa_supplicant = wifi_test_utils.must_be_installed(
                host, '/usr/sbin/wpa_supplicant')
        self.dhcpd_conf = '/tmp/dhcpd.%s.conf'
        self.dhcpd_leases = '/tmp/dhcpd.leases'

        # hostapd configuration persists throughout the test, subsequent
        # 'config' commands only modify it.
        self.ssid_prefix = test_name
        if self.ssid_prefix.startswith(self.KNOWN_TEST_PREFIX):
            # Many of our tests start with an uninteresting prefix.
            # Remove it so we can have more unique bytes.
            self.ssid_prefix = self.ssid_prefix[len(self.KNOWN_TEST_PREFIX):]
        self.ssid_prefix = self.ssid_prefix.lstrip('_')
        self.ssid_prefix += '_'

        self._total_hostapd_instances = 0
        self.local_servers = []
        self.hostapd_instances = []
        self.station_instances = []
        self.dhcp_low = 1
        self.dhcp_high = 128

        # Kill hostapd and dhcp server if already running.
        self.kill_hostapd()
        self.stop_dhcp_servers()

        # Place us in the US by default
        self.iw_runner.set_regulatory_domain('US')

        # Reset all antennas to be active
        self.set_default_antenna_bitmap()


    def close(self):
        """Close global resources held by this system."""
        self.deconfig()
        super(LinuxRouter, self).close()


    def has_local_server(self):
        """@return True iff this router has local servers configured."""
        return bool(self.local_servers)


    def start_hostapd(self, configuration):
        """Start a hostapd instance described by conf.

        @param configuration HostapConfig object.

        """
        # Figure out the correct interface.
        interface = self.get_wlanif(configuration.frequency, 'managed')

        conf_file = self.HOSTAPD_CONF_FILE_PATTERN % interface
        log_file = self.HOSTAPD_LOG_FILE_PATTERN % interface
        pid_file = self.HOSTAPD_PID_FILE_PATTERN % interface
        control_interface = self.HOSTAPD_CONTROL_INTERFACE_PATTERN % interface
        hostapd_conf_dict = configuration.generate_dict(
                interface, control_interface,
                self._build_ssid(configuration.ssid_suffix))
        logging.info('Starting hostapd with parameters: %r', hostapd_conf_dict)

        # Generate hostapd.conf.
        self.router.run("cat <<EOF >%s\n%s\nEOF\n" %
            (conf_file, '\n'.join(
            "%s=%s" % kv for kv in hostapd_conf_dict.iteritems())))

        # Run hostapd.
        logging.info("Starting hostapd...")
        self.router.run('rm %s' % log_file, ignore_status=True)
        self.router.run('rm %s' % pid_file, ignore_status=True)
        self.router.run('stop wpasupplicant', ignore_status=True)
        start_command = '%s -dd -B -t -f %s -P %s %s' % (
                self.cmd_hostapd, log_file, pid_file, conf_file)
        self.router.run(start_command)
        self.hostapd_instances.append({
            'ssid': hostapd_conf_dict['ssid'],
            'conf_file': conf_file,
            'log_file': log_file,
            'interface': interface,
            'pid_file': pid_file,
            'config_dict': hostapd_conf_dict.copy()
        })

        # Wait for confirmation that the router came up.
        pid = int(self.router.run('cat %s' % pid_file).stdout)
        logging.info('Waiting for hostapd to startup.')
        start_time = time.time()
        while time.time() - start_time < self.STARTUP_TIMEOUT_SECONDS:
            success = self.router.run(
                    'grep "Completing interface initialization" %s' % log_file,
                    ignore_status=True).exit_status == 0
            if success:
                break

            # A common failure is an invalid router configuration.
            # Detect this and exit early if we see it.
            bad_config = self.router.run(
                    'grep "Interface initialization failed" %s' % log_file,
                    ignore_status=True).exit_status == 0
            if bad_config:
                raise error.TestFail('hostapd failed to initialize AP '
                                     'interface.')

            if pid:
                early_exit = self.router.run('kill -0 %d' % pid,
                                             ignore_status=True).exit_status
                if early_exit:
                    raise error.TestFail('hostapd process terminated.')

            time.sleep(self.STARTUP_POLLING_INTERVAL_SECONDS)
        else:
            raise error.TestFail('Timed out while waiting for hostapd '
                                 'to start.')


    def _kill_process_instance(self, process, instance=None, wait=0):
        """Kill a process on the router.

        Kills program named |process|, optionally only a specific
        |instance|.  If |wait| is specified, we makes sure |process| exits
        before returning.

        @param process string name of process to kill.
        @param instance string instance of process to kill.
        @param wait int timeout in seconds to wait for.

        """
        if instance:
            search_arg = '-f "%s.*%s"' % (process, instance)
        else:
            search_arg = process

        cmd = "pkill %s >/dev/null 2>&1" % search_arg

        if wait:
            cmd += (" && while pgrep %s &> /dev/null; do sleep 1; done" %
                    search_arg)
            self.router.run(cmd, timeout=wait, ignore_status=True)
        else:
            self.router.run(cmd, ignore_status=True)


    def kill_hostapd_instance(self, instance):
        """Kills a hostapd instance.

        @param instance string instance to kill.

        """
        self._kill_process_instance('hostapd', instance, 30)


    def kill_hostapd(self):
        """Kill all hostapd instances."""
        self.kill_hostapd_instance(None)


    def _build_ssid(self, suffix):
        unique_salt = ''.join([random.choice(self.SUFFIX_LETTERS)
                               for x in range(5)])
        return (self.ssid_prefix + unique_salt + suffix)[-32:]


    def hostap_configure(self, configuration, multi_interface=None):
        """Build up a hostapd configuration file and start hostapd.

        Also setup a local server if this router supports them.

        @param configuration HosetapConfig object.
        @param multi_interface bool True iff multiple interfaces allowed.

        """
        if multi_interface is None and (self.hostapd_instances or
                                        self.station_instances):
            self.deconfig()
        self.start_hostapd(configuration)
        interface = self.hostapd_instances[-1]['interface']
        self.iw_runner.set_tx_power(interface, 'auto')
        self.start_local_server(interface)
        logging.info('AP configured.')


    def ibss_configure(self, config):
        """Configure a station based AP in IBSS mode.

        Extract relevant configuration objects from |config| despite not
        actually being a hostap managed endpoint.

        @param config HostapConfig object.

        """
        if self.station_instances or self.hostapd_instances:
            self.deconfig()
        interface = self.get_wlanif(config.frequency, 'ibss')
        ssid = (config.ssid or self._build_ssid(config.ssid_suffix))
        # Connect the station
        self.router.run('%s link set %s up' % (self.cmd_ip, interface))
        self.iw_runner.ibss_join(interface, ssid, config.frequency)
        # Always start a local server.
        self.start_local_server(interface)
        # Remember that this interface is up.
        self.station_instances.append(
                StationInstance(ssid=ssid, interface=interface,
                                dev_type='ibss'))


    def local_server_address(self, index):
        """Get the local server address for an interface.

        When we multiple local servers, we give them static IP addresses
        like 192.168.*.254.

        @param index int describing which local server this is for.

        """
        return '%d.%d.%d.%d' % (self.SUBNET_PREFIX_OCTETS + (index, 254))


    def local_peer_ip_address(self, index):
        """Get the IP address allocated for the peer associated to the AP.

        This address is assigned to a locally associated peer device that
        is created for the DUT to perform connectivity tests with.
        When we have multiple local servers, we give them static IP addresses
        like 192.168.*.253.

        @param index int describing which local server this is for.

        """
        return '%d.%d.%d.%d' % (self.SUBNET_PREFIX_OCTETS + (index, 253))


    def local_peer_mac_address(self):
        """Get the MAC address of the peer interface.

        @return string MAC address of the peer interface.

        """
        iface = interface.Interface(self.station_instances[0].interface,
                                    self.router)
        return iface.mac_address


    def start_local_server(self, interface):
        """Start a local server on an interface.

        @param interface string (e.g. wlan0)

        """
        logging.info('Starting up local server...')

        if len(self.local_servers) >= 256:
            raise error.TestFail('Exhausted available local servers')

        server_addr = netblock.Netblock.from_addr(
                self.local_server_address(len(self.local_servers)),
                prefix_len=24)

        params = {}
        params['netblock'] = server_addr
        params['dhcp_range'] = ' '.join(
            (server_addr.get_addr_in_block(1),
             server_addr.get_addr_in_block(128)))
        params['interface'] = interface
        params['ip_params'] = ('%s broadcast %s dev %s' %
                               (server_addr.netblock,
                                server_addr.broadcast,
                                interface))
        self.local_servers.append(params)

        self.router.run('%s addr flush %s' %
                        (self.cmd_ip, interface))
        self.router.run('%s addr add %s' %
                        (self.cmd_ip, params['ip_params']))
        self.router.run('%s link set %s up' %
                        (self.cmd_ip, interface))
        self.start_dhcp_server(interface)


    def start_dhcp_server(self, interface):
        """Start a dhcp server on an interface.

        @param interface string (e.g. wlan0)

        """
        for server in self.local_servers:
            if server['interface'] == interface:
                params = server
                break
        else:
            raise error.TestFail('Could not find local server '
                                 'to match interface: %r' % interface)
        server_addr = params['netblock']
        dhcpd_conf_file = self.dhcpd_conf % interface
        dhcp_conf = '\n'.join([
            'port=0',  # disables DNS server
            'bind-interfaces',
            'log-dhcp',
            'dhcp-range=%s' % ','.join((server_addr.get_addr_in_block(1),
                                        server_addr.get_addr_in_block(128))),
            'interface=%s' % params['interface'],
            'dhcp-leasefile=%s' % self.dhcpd_leases])
        self.router.run('cat <<EOF >%s\n%s\nEOF\n' %
            (dhcpd_conf_file, dhcp_conf))
        self.router.run('dnsmasq --conf-file=%s' % dhcpd_conf_file)


    def stop_dhcp_server(self, instance=None):
        """Stop a dhcp server on the router.

        @param instance string instance to kill.

        """
        self._kill_process_instance('dnsmasq', instance, 0)


    def stop_dhcp_servers(self):
        """Stop all dhcp servers on the router."""
        self.stop_dhcp_server(None)


    def get_wifi_channel(self, ap_num):
        """Return channel of BSS corresponding to |ap_num|.

        @param ap_num int which BSS to get the channel of.
        @return int primary channel of BSS.

        """
        instance = self.hostapd_instances[ap_num]
        return instance['config_dict']['channel']


    def get_wifi_ip(self, ap_num):
        """Return IP address on the WiFi subnet of a local server on the router.

        If no local servers are configured (e.g. for an RSPro), a TestFail will
        be raised.

        @param ap_num int which local server to get an address from.

        """
        if not self.local_servers:
            raise error.TestError('No IP address assigned')

        return self.local_servers[ap_num]['netblock'].addr


    def get_wifi_ip_subnet(self, ap_num):
        """Return subnet of WiFi AP instance.

        If no APs are configured a TestError will be raised.

        @param ap_num int which local server to get an address from.

        """
        if not self.local_servers:
            raise error.TestError('No APs configured.')

        return self.local_servers[ap_num]['netblock'].subnet


    def get_hostapd_interface(self, ap_num):
        """Get the name of the interface associated with a hostapd instance.

        @param ap_num: int hostapd instance number.
        @return string interface name (e.g. 'managed0').

        """
        if ap_num not in range(len(self.hostapd_instances)):
            raise error.TestFail('Invalid instance number (%d) with %d '
                                 'instances configured.' %
                                 (ap_num, len(self.hostapd_instances)))

        instance = self.hostapd_instances[ap_num]
        return instance['interface']


    def get_hostapd_mac(self, ap_num):
        """Return the MAC address of an AP in the test.

        @param ap_num int index of local server to read the MAC address from.
        @return string MAC address like 00:11:22:33:44:55.

        """
        interface_name = self.get_hostapd_interface(ap_num)
        ap_interface = interface.Interface(interface_name, self.host)
        return ap_interface.mac_address


    def get_hostapd_phy(self, ap_num):
        """Get name of phy for hostapd instance.

        @param ap_num int index of hostapd instance.
        @return string phy name of phy corresponding to hostapd's
                managed interface.

        """
        interface = self.iw_runner.get_interface(
                self.get_hostapd_interface(ap_num))
        return interface.phy


    def deconfig(self):
        """A legacy, deprecated alias for deconfig_aps."""
        self.deconfig_aps()


    def deconfig_aps(self, instance=None, silent=False):
        """De-configure an AP (will also bring wlan down).

        @param instance: int or None.  If instance is None, will bring down all
                instances of hostapd.
        @param silent: True if instances should be brought without de-authing
                the DUT.

        """
        if not self.hostapd_instances and not self.station_instances:
            return

        if self.hostapd_instances:
            local_servers = []
            if instance is not None:
                instances = [ self.hostapd_instances.pop(instance) ]
                for server in self.local_servers:
                    if server['interface'] == instances[0]['interface']:
                        local_servers = [server]
                        self.local_servers.remove(server)
                        break
            else:
                instances = self.hostapd_instances
                self.hostapd_instances = []
                local_servers = self.local_servers
                self.local_servers = []

            for instance in instances:
                if silent:
                    # Deconfigure without notifying DUT.  Remove the interface
                    # hostapd uses to send beacon and DEAUTH packets.
                    self.remove_interface(instance['interface'])

                self.kill_hostapd_instance(instance['conf_file'])
                if wifi_test_utils.is_installed(self.host,
                                                instance['log_file']):
                    self.router.get_file(instance['log_file'],
                                         'debug/hostapd_router_%d_%s.log' %
                                         (self._total_hostapd_instances,
                                          instance['interface']))
                else:
                    logging.error('Did not collect hostapd log file because '
                                  'it was missing.')
                self.release_interface(instance['interface'])
#               self.router.run("rm -f %(log_file)s %(conf_file)s" % instance)
            self._total_hostapd_instances += 1
        if self.station_instances:
            local_servers = self.local_servers
            self.local_servers = []
            instance = self.station_instances.pop()
            if instance.dev_type == 'ibss':
                self.iw_runner.ibss_leave(instance.interface)
            elif instance.dev_type == 'managed':
                self._kill_process_instance('wpa_supplicant',
                                            instance.interface)
            else:
                self.iw_runner.disconnect_station(instance.interface)
            self.router.run('%s link set %s down' %
                            (self.cmd_ip, instance.interface))

        for server in local_servers:
            self.stop_dhcp_server(server['interface'])
            self.router.run("%s addr del %s" %
                            (self.cmd_ip, server['ip_params']),
                             ignore_status=True)


    def confirm_pmksa_cache_use(self, instance=0):
        """Verify that the PMKSA auth was cached on a hostapd instance.

        @param instance int router instance number.

        """
        log_file = self.hostapd_instances[instance]['log_file']
        pmksa_match = 'PMK from PMKSA cache'
        result = self.router.run('grep -q "%s" %s' % (pmksa_match, log_file),
                                 ignore_status=True)
        if result.exit_status:
            raise error.TestFail('PMKSA cache was not used in roaming.')


    def get_ssid(self, instance=None):
        """@return string ssid for the network stemming from this router."""
        if instance is None:
            instance = 0
            if len(self.hostapd_instances) > 1:
                raise error.TestFail('No instance of hostapd specified with '
                                     'multiple instances present.')

        if self.hostapd_instances:
            return self.hostapd_instances[instance]['ssid']

        if self.station_instances:
            return self.station_instances[0].ssid

        raise error.TestFail('Requested ssid of an unconfigured AP.')


    def deauth_client(self, client_mac):
        """Deauthenticates a client described in params.

        @param client_mac string containing the mac address of the client to be
               deauthenticated.

        """
        control_if = self.hostapd_instances[-1]['config_dict']['ctrl_interface']
        self.router.run('%s -p%s deauthenticate %s' %
                        (self.cmd_hostapd_cli, control_if, client_mac))


    def send_management_frame_on_ap(self, frame_type, channel, instance=0):
        """Injects a management frame into an active hostapd session.

        @param frame_type string the type of frame to send.
        @param channel int targeted channel
        @param instance int indicating which hostapd instance to inject into.

        """
        hostap_interface = self.hostapd_instances[instance]['interface']
        interface = self.get_wlanif(0, 'monitor', same_phy_as=hostap_interface)
        self.router.run("%s link set %s up" % (self.cmd_ip, interface))
        self.router.run('%s -i %s -t %s -c %d' %
                        (self.cmd_send_management_frame, interface, frame_type,
                         channel))
        self.release_interface(interface)


    def setup_management_frame_interface(self, channel):
        """
        Setup interface for injecting management frames.

        @param channel int channel to inject the frames.

        @return string name of the interface.

        """
        frequency = hostap_config.HostapConfig.get_frequency_for_channel(
                channel)
        interface = self.get_wlanif(frequency, 'monitor')
        self.iw_runner.set_freq(interface, frequency)
        self.router.run('%s link set %s up' % (self.cmd_ip, interface))
        return interface


    def send_management_frame(self, interface, frame_type, channel,
                              ssid_prefix=None, num_bss=None,
                              frame_count=None, delay=None):
        """
        Injects management frames on specify channel |frequency|.

        This function will spawn off a new process to inject specified
        management frames |frame_type| at the specified interface |interface|.

        @param interface string interface to inject frames.
        @param frame_type string message type.
        @param channel int targeted channel.
        @param ssid_prefix string SSID prefix.
        @param num_bss int number of BSS.
        @param frame_count int number of frames to send.
        @param delay int milliseconds delay between frames.

        @return int PID of the newly created process.

        """
        command = '%s -i %s -t %s -c %d' % (self.cmd_send_management_frame,
                                interface, frame_type, channel)
        if ssid_prefix is not None:
            command += ' -s %s' % (ssid_prefix)
        if num_bss is not None:
            command += ' -b %d' % (num_bss)
        if frame_count is not None:
            command += ' -n %d' % (frame_count)
        if delay is not None:
            command += ' -d %d' % (delay)
        command += ' > %s 2>&1 & echo $!' % (self.MGMT_FRAME_SENDER_LOG_FILE)
        pid = int(self.router.run(command).stdout)
        return pid


    def detect_client_deauth(self, client_mac, instance=0):
        """Detects whether hostapd has logged a deauthentication from
        |client_mac|.

        @param client_mac string the MAC address of the client to detect.
        @param instance int indicating which hostapd instance to query.

        """
        interface = self.hostapd_instances[instance]['interface']
        deauth_msg = "%s: deauthentication: STA=%s" % (interface, client_mac)
        log_file = self.hostapd_instances[instance]['log_file']
        result = self.router.run("grep -qi '%s' %s" % (deauth_msg, log_file),
                                 ignore_status=True)
        return result.exit_status == 0


    def detect_client_coexistence_report(self, client_mac, instance=0):
        """Detects whether hostapd has logged an action frame from
        |client_mac| indicating information about 20/40MHz BSS coexistence.

        @param client_mac string the MAC address of the client to detect.
        @param instance int indicating which hostapd instance to query.

        """
        coex_msg = ('nl80211: MLME event frame - hexdump(len=.*): '
                    '.. .. .. .. .. .. .. .. .. .. %s '
                    '.. .. .. .. .. .. .. .. 04 00.*48 01 ..' %
                    ' '.join(client_mac.split(':')))
        log_file = self.hostapd_instances[instance]['log_file']
        result = self.router.run("grep -qi '%s' %s" % (coex_msg, log_file),
                                 ignore_status=True)
        return result.exit_status == 0


    def add_connected_peer(self, instance=0):
        """Configure a station connected to a running AP instance.

        Extract relevant configuration objects from the hostap
        configuration for |instance| and generate a wpa_supplicant
        instance that connects to it.  This allows the DUT to interact
        with a client entity that is also connected to the same AP.  A
        full wpa_supplicant instance is necessary here (instead of just
        using the "iw" command to connect) since we want to enable
        advanced features such as TDLS.

        @param instance int indicating which hostapd instance to connect to.

        """
        if not self.hostapd_instances:
            raise error.TestFail('Hostapd is not configured.')

        if self.station_instances:
            raise error.TestFail('Station is already configured.')

        ssid = self.get_ssid(instance)
        hostap_conf = self.hostapd_instances[instance]['config_dict']
        frequency = hostap_config.HostapConfig.get_frequency_for_channel(
                hostap_conf['channel'])
        interface = self.get_wlanif(frequency, 'managed')

        # TODO(pstew): Configure other bits like PSK, 802.11n if tests
        # require them...
        supplicant_config = (
                'network={\n'
                '  ssid="%(ssid)s"\n'
                '  key_mgmt=NONE\n'
                '}\n' % {'ssid': ssid}
        )

        conf_file = self.STATION_CONF_FILE_PATTERN % interface
        log_file = self.STATION_LOG_FILE_PATTERN % interface
        pid_file = self.STATION_PID_FILE_PATTERN % interface

        self.router.run('cat <<EOF >%s\n%s\nEOF\n' %
            (conf_file, supplicant_config))

        # Connect the station.
        self.router.run('%s link set %s up' % (self.cmd_ip, interface))
        start_command = ('%s -dd -t -i%s -P%s -c%s -D%s &> %s &' %
                         (self.cmd_wpa_supplicant,
                         interface, pid_file, conf_file,
                         self.HOSTAPD_DRIVER_NAME, log_file))
        self.router.run(start_command)
        self.iw_runner.wait_for_link(interface)

        # Assign an IP address to this interface.
        self.router.run('%s addr add %s/24 dev %s' %
                        (self.cmd_ip, self.local_peer_ip_address(instance),
                         interface))

        # Since we now have two network interfaces connected to the same
        # network, we need to disable the kernel's protection against
        # incoming packets to an "unexpected" interface.
        self.router.run('echo 2 > /proc/sys/net/ipv4/conf/%s/rp_filter' %
                        interface)

        # Similarly, we'd like to prevent the hostap interface from
        # replying to ARP requests for the peer IP address and vice
        # versa.
        self.router.run('echo 1 > /proc/sys/net/ipv4/conf/%s/arp_ignore' %
                        interface)
        self.router.run('echo 1 > /proc/sys/net/ipv4/conf/%s/arp_ignore' %
                        hostap_conf['interface'])

        self.station_instances.append(
                StationInstance(ssid=ssid, interface=interface,
                                dev_type='managed'))
