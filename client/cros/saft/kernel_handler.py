#!/usr/bin/python
# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

'''A module containing kernel handler class used by SAFT.'''

import os
import re

TMP_FILE_NAME = 'kernel_header_dump'

# Types of kernel modifications.
KERNEL_BODY_MOD = 1
KERNEL_VERSION_MOD = 2
KERNEL_RESIGN_MOD = 3


class KernelHandlerError(Exception):
    pass


class KernelHandler(object):
    '''An object to provide ChromeOS kernel related actions.

    Mostly it allows to corrupt and restore a particular kernel partition
    (designated by the partition name, A or B.
    '''

    # This value is used to alter contents of a byte in the appropriate kernel
    # image. First added to corrupt the image, then subtracted to restore the
    # image.
    DELTA = 1

    def __init__(self):
        self.chros_if = None
        self.dump_file_name = None
        self.partition_map = {}
        self.root_dev = None

    def _get_version(self, device):
        '''Get version of the kernel hosted on the passed in partition.'''
        # 16 K should be enough to include headers and keys
        data = self.chros_if.read_partition(device, 0x4000)
        return self.chros_if.retrieve_body_version(data)

    def _get_datakey_version(self,device):
        '''Get datakey version of kernel hosted on the passed in partition.'''
        # 16 K should be enought to include headers and keys
        data = self.chros_if.read_partition(device, 0x4000)
        return self.chros_if.retrieve_datakey_version(data)

    def _get_partition_map(self, internal_disk=True):
        '''Scan `cgpt show <device> output to find kernel devices.

        Args:
          internal_disk - decide whether to use internal kernel disk.
        '''
        if internal_disk:
            target_device = self.chros_if.get_internal_disk(
                    self.chros_if.get_root_part())
        else:
            target_device = self.root_dev

        kernel_partitions = re.compile('KERN-([AB])')
        disk_map = self.chros_if.run_shell_command_get_output(
            'cgpt show %s' % target_device)

        for line in disk_map:
            matched_line = kernel_partitions.search(line)
            if not matched_line:
                continue
            label = matched_line.group(1)
            part_info = {}
            device = self.chros_if.join_part(target_device, line.split()[2])
            part_info['device'] = device
            part_info['version'] = self._get_version(device)
            part_info['datakey_version'] = self._get_datakey_version(device)
            self.partition_map[label] = part_info

    def _modify_kernel(self, section,
                       delta,
                       modification_type=KERNEL_BODY_MOD,
                       key_path=None):
        '''Modify kernel image on a disk partition.

        This method supports three types of kernel modification. KERNEL_BODY_MOD
        just adds the value of delta to the first byte of the kernel blob.
        This might leave the kernel corrupted (as required by the test).

        The second type, KERNEL_VERSION_MOD - will use 'delta' as the new
        version number, it will put it in the kernel header, and then will
        resign the kernel blob.

        The third type. KERNEL_RESIGN_MOD - will resign the kernel with keys in
        argument key_path. If key_path is None, choose dev_key_path as resign
        key directory.
        '''
        dev = self.partition_map[section]['device']
        cmd_template = 'dd if=%s of=%s bs=4M count=1'
        self.chros_if.run_shell_command(cmd_template % (
                dev, self.dump_file_name))
        bfile = open(self.dump_file_name, 'r')
        data = list(bfile.read())
        bfile.close()
        if modification_type == KERNEL_BODY_MOD:
            data[0] = '%c' % ((ord(data[0]) + delta) % 0x100)
            dumpf = open(self.dump_file_name, 'w')
            dumpf.write(''.join(data))
            dumpf.close()
            kernel_to_write = self.dump_file_name
        elif modification_type == KERNEL_VERSION_MOD:
            new_version = delta
            kernel_to_write = self.dump_file_name + '.new'
            self.chros_if.run_shell_command(
                'vbutil_kernel --repack %s --version %d '
                '--signprivate %s --oldblob %s' % (
                    kernel_to_write, new_version,
                    os.path.join(self.dev_key_path, 'kernel_data_key.vbprivk'),
                    self.dump_file_name))
        elif modification_type == KERNEL_RESIGN_MOD:
            if key_path and os.path.isdir(key_path):
                resign_key_path = key_path
            else:
                resign_key_path = self.dev_key_path

            kernel_to_write = self.dump_file_name + '.new'
            self.chros_if.run_shell_command(
                'vbutil_kernel --repack %s '
                '--signprivate %s --oldblob %s --keyblock %s' % (
                    kernel_to_write,
                    os.path.join(resign_key_path, 'kernel_data_key.vbprivk'),
                    self.dump_file_name,
                    os.path.join(resign_key_path, 'kernel.keyblock')))
        else:
            return  # Unsupported mode, ignore.
        self.chros_if.run_shell_command(cmd_template % (kernel_to_write, dev))

    def corrupt_kernel(self, section):
        '''Corrupt a kernel section (add DELTA to the first byte).'''
        self._modify_kernel(section.upper(), self.DELTA)

    def restore_kernel(self, section):
        '''Restore the previously corrupted kernel.'''
        self._modify_kernel(section.upper(), -self.DELTA)

    def get_version(self, section):
        '''Return version read from this section blob's header.'''
        return self.partition_map[section.upper()]['version']

    def get_datakey_version(self, section):
        '''Return datakey version read from this section blob's header.'''
        return self.partition_map[section.upper()]['datakey_version']

    def set_version(self, section, version):
        '''Set version of this kernel blob and re-sign it.'''
        if version < 0:
            raise KernelHandlerError('Bad version value %d' % version)
        self._modify_kernel(section.upper(), version, KERNEL_VERSION_MOD)

    def resign_kernel(self, section, key_path=None):
        """Resign kernel with original kernel version and keys in key_path."""
        self._modify_kernel(section.upper(),
                            self.get_version(section),
                            KERNEL_RESIGN_MOD,
                            key_path)

    def init(self, chros_if, dev_key_path='.', internal_disk=True):
        '''Initialize the kernel handler object.

        Input argument is a ChromeOS interface object reference.
        '''
        self.chros_if = chros_if
        self.dev_key_path = dev_key_path
        self.root_dev = chros_if.get_root_dev()
        self.dump_file_name = chros_if.state_dir_file(TMP_FILE_NAME)
        self._get_partition_map(internal_disk)
