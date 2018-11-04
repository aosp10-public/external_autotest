# Copyright (c) 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import time

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib import file_utils
from autotest_lib.client.common_lib.cros import system_metrics_collector
from autotest_lib.client.common_lib.cros.cfm.metrics import (
        media_metrics_collector)
from autotest_lib.server.cros.cfm import cfm_base_test
from autotest_lib.server.cros.cfm.utils import bond_http_api


_SHORT_TIMEOUT = 5
_MEASUREMENT_DURATION_SECONDS = 10
_TOTAL_TEST_DURATION_SECONDS = 900 # 15 minutes
_BOT_PARTICIPANTS_COUNT = 10

_DOWNLOAD_BASE = ('http://commondatastorage.googleapis.com/'
                  'chromiumos-test-assets-public/crowd/')
_VIDEO_NAME = 'crowd720_25frames.y4m'


class ParticipantCountMetric(system_metrics_collector.Metric):
    """
    Metric for getting the current participant count in a call.
    """
    def __init__(self, cfm_facade):
        """
        Initializes with a cfm_facade.

        @param cfm_facade object having a get_participant_count() method.
        """
        super(ParticipantCountMetric, self).__init__(
                'participant_count',
                'participants',
                higher_is_better=True)
        self.cfm_facade = cfm_facade

    def collect_metric(self):
        """
        Collects one metric value.
        """
        self.values.append(self.cfm_facade.get_participant_count())


class enterprise_CFM_Perf(cfm_base_test.CfmBaseTest):
    """This is a server test which clears device TPM and runs
    enterprise_RemoraRequisition client test to enroll the device in to hotrod
    mode. After enrollment is successful, it collects and logs cpu, memory and
    temperature data from the device under test."""
    version = 1

    def start_meeting(self):
        """Waits for the landing page and starts a meeting.

        @return: The code for the started meeting.
        """
        self.cfm_facade.wait_for_meetings_landing_page()
        return self.cfm_facade.start_meeting_session()

    def collect_perf_data(self):
        """
        Collects run time data from the DUT using system_metrics_collector.
        Writes the data to the chrome perf dashboard.
        """
        start_time = time.time()
        while (time.time() - start_time) < _TOTAL_TEST_DURATION_SECONDS:
            time.sleep(_MEASUREMENT_DURATION_SECONDS)
            self.metrics_collector.collect_snapshot()
            self.media_metrics_collector.collect_snapshot()
        self.metrics_collector.write_metrics(self.output_perf_value)

    def _get_average(self, data_type):
        """Computes mean of a list of numbers.

        @param data_type: Type of data to be retrieved from jmi data log.
        @return Mean computed from the list of numbers.
        """
        data = self._get_jmi_data(data_type)
        if not data:
            return 0
        return float(sum(data)) / len(data)


    def _get_max_value(self, data_type):
        """Computes maximum value of a list of numbers.

        @param data_type: Type of data to be retrieved from jmi data log.
        @return Maxium value from the list of numbers.
        """
        data = self._get_jmi_data(data_type)
        if not data:
            return 0
        return max(data)


    def _get_sum(self, data_type):
        """Computes sum of a list of numbers.

        @param data_type: Type of data to be retrieved from jmi data log.
        @return Sum computed from the list of numbers.
        """
        data = self._get_jmi_data(data_type)
        if not data:
            return 0
        return sum(data)


    def _get_last_value(self, data_type):
        """Gets last value of a list of numbers.

        @param data_type: Type of data to be retrieved from jmi data log.
        @return The last value in the jmidata for the specified data_type. 0 if
                there are no values in the jmidata for this data_type.
        """
        data = self._get_jmi_data(data_type)
        if not data:
            return 0
        return data[-1]


    def _get_jmi_data(self, data_type):
        """Gets jmi data for the given data type.

        @param data_type: Type of data to be retrieved from jmi data logs.
        @return Data for given data type from jmidata log.
        """
        try:
            timestamped_values = self.media_metrics_collector.get_metric(
                    data_type)
        except KeyError:
            # Ensure we always return at least one element, or perf uploads
            # will be sad.
            return [0]
        # Strip timestamps.
        values = [x[1] for x in timestamped_values]
        # Each entry in values is a list, extract the raw values:
        res = []
        for value_list in values:
            res.extend(value_list)
        # Ensure we always return at least one element, or perf uploads will
        # be sad.
        return res or [0]

    def upload_jmidata(self):
        """
        Write jmidata results to results-chart.json file for Perf Dashboard.
        """
        # Compute and save aggregated stats from JMI.
        self.output_perf_value(description='sum_vid_in_frames_decoded',
                value=self._get_sum('frames_decoded'), units='frames',
                higher_is_better=True)

        self.output_perf_value(description='sum_vid_out_frames_encoded',
                value=self._get_sum('frames_encoded'), units='frames',
                higher_is_better=True)

        self.output_perf_value(description='vid_out_adapt_changes',
                value=self._get_last_value('adaptation_changes'),
                units='count', higher_is_better=False)

        self.output_perf_value(description='video_out_encode_time',
                value=self._get_jmi_data('average_encode_time'),
                units='ms', higher_is_better=False)

        self.output_perf_value(description='max_video_out_encode_time',
                value=self._get_max_value('average_encode_time'),
                units='ms', higher_is_better=False)

        self.output_perf_value(description='vid_out_bandwidth_adapt',
                value=self._get_average('bandwidth_adaptation'),
                units='bool', higher_is_better=False)

        self.output_perf_value(description='vid_out_cpu_adapt',
                value=self._get_average('cpu_adaptation'),
                units='bool', higher_is_better=False)

        self.output_perf_value(description='video_in_res',
                value=self._get_jmi_data(
                        'video_received_frame_height'),
                units='px', higher_is_better=True)

        self.output_perf_value(description='video_out_res',
                value=self._get_jmi_data('video_sent_frame_height'),
                units='resolution', higher_is_better=True)

        self.output_perf_value(description='vid_in_framerate_decoded',
                value=self._get_jmi_data('framerate_decoded'),
                units='fps', higher_is_better=True)

        self.output_perf_value(description='vid_out_framerate_input',
                value=self._get_jmi_data('framerate_outgoing'),
                units='fps', higher_is_better=True)

        self.output_perf_value(description='vid_in_framerate_to_renderer',
                value=self._get_jmi_data('framerate_to_renderer'),
                units='fps', higher_is_better=True)

        self.output_perf_value(description='vid_in_framerate_received',
                value=self._get_jmi_data('framerate_received'),
                units='fps', higher_is_better=True)

        self.output_perf_value(description='vid_out_framerate_sent',
                value=self._get_jmi_data('framerate_sent'),
                units='fps', higher_is_better=True)

        self.output_perf_value(description='vid_in_frame_width',
                value=self._get_jmi_data('video_received_frame_width'),
                units='px', higher_is_better=True)

        self.output_perf_value(description='vid_out_frame_width',
                value=self._get_jmi_data('video_sent_frame_width'),
                units='px', higher_is_better=True)

        self.output_perf_value(description='vid_out_encode_cpu_usage',
                value=self._get_jmi_data('video_encode_cpu_usage'),
                units='percent', higher_is_better=False)

        total_vid_packets_sent = self._get_sum('video_packets_sent')
        total_vid_packets_lost = self._get_sum('video_packets_lost')
        lost_packet_percentage = float(total_vid_packets_lost)*100/ \
                                 float(total_vid_packets_sent) if \
                                 total_vid_packets_sent else 0

        self.output_perf_value(description='lost_packet_percentage',
                value=lost_packet_percentage, units='percent',
                higher_is_better=False)
        self.output_perf_value(description='cpu_usage_jmi',
                value=self._get_jmi_data('cpu_percent'),
                units='percent', higher_is_better=False)
        self.output_perf_value(description='renderer_cpu_usage',
                value=self._get_jmi_data('renderer_cpu_percent'),
                units='percent', higher_is_better=False)
        self.output_perf_value(description='browser_cpu_usage',
                value=self._get_jmi_data('browser_cpu_percent'),
                units='percent', higher_is_better=False)

        self.output_perf_value(description='gpu_cpu_usage',
                value=self._get_jmi_data('gpu_cpu_percent'),
                units='percent', higher_is_better=False)

        self.output_perf_value(description='active_streams',
                value=self._get_jmi_data('num_active_vid_in_streams'),
                units='count', higher_is_better=True)

    def _download_test_video(self):
        """
        Downloads the test video to a temporary directory on host.

        @return the remote path of the downloaded video.
        """
        url = _DOWNLOAD_BASE + _VIDEO_NAME
        local_path = os.path.join(self.tmpdir, _VIDEO_NAME)
        logging.info('Downloading %s to %s', url, local_path)
        file_utils.download_file(url, local_path)
        # The directory returned by get_tmp_dir() is automatically deleted.
        tmp_dir = self._host.get_tmp_dir()
        remote_path = os.path.join(tmp_dir, _VIDEO_NAME)
        # The temporary directory has mode 700 by default. Chrome runs with a
        # different user so cannot access it unless we change the permissions.
        logging.info('chmodding tmpdir %s to 755', tmp_dir)
        self._host.run('chmod 755 %s' % tmp_dir)
        logging.info('Sending %s to %s on DUT', local_path, remote_path)
        self._host.send_file(local_path, remote_path)
        os.remove(local_path)
        return remote_path

    def initialize(self, host, run_test_only=False):
        """
        Initializes common test properties.

        @param host: a host object representing the DUT.
        @param run_test_only: Wheter to run only the test or to also perform
            deprovisioning, enrollment and system reboot. See cfm_base_test.
        """
        super(enterprise_CFM_Perf, self).initialize(host, run_test_only)
        self._host = host
        self.system_facade = self._facade_factory.create_system_facade()
        metrics = system_metrics_collector.create_default_metric_set(
                self.system_facade)
        metrics.append(ParticipantCountMetric(self.cfm_facade))
        self.metrics_collector = (system_metrics_collector.
                                  SystemMetricsCollector(self.system_facade,
                                                         metrics))
        data_point_collector = media_metrics_collector.DataPointCollector(
                self.cfm_facade)
        self.media_metrics_collector = (media_metrics_collector
                                        .MetricsCollector(data_point_collector))

    def setup(self):
        """
        Download video for fake media and restart Chrome with fake media flags.

        This runs after initialize().
        """
        super(enterprise_CFM_Perf, self).setup()
        remote_video_path = self._download_test_video()
        # Restart chrome with fake media flags.
        extra_chrome_args=[
                '--use-fake-device-for-media-stream',
                '--use-file-for-fake-video-capture=%s' % remote_video_path
        ]
        self.cfm_facade.restart_chrome_for_cfm(extra_chrome_args)
        self.bond = bond_http_api.BondHttpApi()

    def run_once(self):
        """Stays in a meeting and collects perf data."""
        meeting_code = self.start_meeting()
        logging.info('Started meeting "%s"', meeting_code)
        self._add_bots(_BOT_PARTICIPANTS_COUNT, meeting_code)
        self.cfm_facade.unmute_mic()
        self.collect_perf_data()
        self.cfm_facade.end_meeting_session()
        self.upload_jmidata()

    def _add_bots(self, bot_count, meeting_code):
        """Adds bots to a meeting and configures audio and pinning settings.

        If we were not able to start enough bots end the test run.
        """
        botIds = self.bond.AddBotsRequest(
            meeting_code,
            bot_count,
            _TOTAL_TEST_DURATION_SECONDS + 30);

        if len(botIds) < bot_count:
            # If we did not manage to start enough bots, free up the
            # resources and end the test run.
            self.bond.ExecuteScript('@all leave', meeting_code)
            raise error.TestNAError("Not enough bot resources.\n"
                "Wanted: %d. Started: %d" % (bot_count, len(botIds)))

        # Configure philosopher audio for one bot.
        self._start_philosopher_audio(botIds[0], meeting_code)

        # Pin the CfM from one bot so the device always sends HD.
        self.bond.ExecuteScript(
            '@b%d pin_participant_by_name "Unknown"' % botIds[0], meeting_code)
        # Explicitly request HD video from the CfM.
        self.bond.ExecuteScript(
            '@b%d set_resolution 1280 720' % botIds[0], meeting_code)

    def _start_philosopher_audio(self, bot_id, meeting_code):
        self.bond.ExecuteScript(
            '@b%d start_philosopher_audio' % bot_id, meeting_code)
