# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper for running suites of tests and waiting for completion."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import sys

import logging
import logging.config

from lucifer import autotest
from skylab_suite import cros_suite
from skylab_suite import suite_parser
from skylab_suite import suite_runner
from skylab_suite import suite_tracking


PROVISION_SUITE_NAME = 'provision'


def setup_logging():
    """Setup the logging for skylab suite."""
    logging.config.dictConfig({
        'version': 1,
        'formatters': {
            'default': {'format': '%(asctime)s %(levelname)-5s| %(message)s'},
        },
        'handlers': {
            'screen': {
                'class': 'logging.StreamHandler',
                'formatter': 'default',
            },
        },
        'root': {
            'level': 'INFO',
            'handlers': ['screen'],
        },
        'disable_existing_loggers': False,
    })


def _parse_suite_specs(options):
    suite_common = autotest.load('server.cros.dynamic_suite.suite_common')
    builds = suite_common.make_builds_from_options(options)
    return cros_suite.SuiteSpecs(
            builds=builds,
            suite_name=options.suite_name,
            suite_file_name=suite_common.canonicalize_suite_name(
                    options.suite_name),
            test_source_build=suite_common.get_test_source_build(
                    builds, test_source_build=options.test_source_build),
            suite_args=options.suite_args,
            priority=options.priority,
            board=options.board,
            pool=options.pool,
    )


def _parse_suite_handler_specs(options):
    provision_num_required = 0
    if 'num_required' in options.suite_args:
        provision_num_required = options.suite_args['num_required']

    return cros_suite.SuiteHandlerSpecs(
            timeout_mins=options.timeout_mins,
            test_retry=options.test_retry,
            max_retries=options.max_retries,
            provision_num_required=provision_num_required)


def _run_suite(options):
    logging.info('Kicked off suite %s', options.suite_name)
    suite_specs = _parse_suite_specs(options)
    if options.suite_name == PROVISION_SUITE_NAME:
        suite_job = cros_suite.ProvisionSuite(suite_specs)
    else:
        suite_job = cros_suite.Suite(suite_specs)

    suite_job.prepare()
    suite_handler_specs = _parse_suite_handler_specs(options)
    suite_handler = cros_suite.SuiteHandler(suite_handler_specs)
    suite_runner.run(suite_job.tests_specs,
                     suite_handler,
                     options.dry_run)
    return_code = suite_tracking.log_suite_results(
            suite_job.suite_name, suite_handler)

    run_suite_common = autotest.load('site_utils.run_suite_common')
    return run_suite_common.SuiteResult(return_code)


def parse_args():
    """Parse & validate skylab suite args."""
    parser = suite_parser.make_parser()
    options = parser.parse_args()
    if options.do_nothing:
        logging.info('Exit early because --do_nothing requested.')
        sys.exit(0)

    if not suite_parser.verify_and_clean_options(options):
        parser.print_help()
        sys.exit(1)

    return options


def main():
    """Entry point."""
    autotest.monkeypatch()

    options = parse_args()
    setup_logging()
    result = _run_suite(options)
    logging.info('Will return from %s with status: %s',
                 os.path.basename(__file__), result.string_code)
    return result.return_code


if __name__ == "__main__":
    sys.exit(main())
