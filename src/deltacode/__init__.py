#
# Copyright (c) 2017 nexB Inc. and others. All rights reserved.
# http://nexb.com and https://github.com/nexB/deltacode/
# The DeltaCode software is licensed under the Apache License version 2.0.
# Data generated with DeltaCode require an acknowledgment.
# DeltaCode is a trademark of nexB Inc.
#
# You may not use this software except in compliance with the License.
# You may obtain a copy of the License at: http://apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
#
# When you publish or redistribute any data created with DeltaCode or any DeltaCode
# derivative work, you must accompany this data with the following acknowledgment:
#
#  Generated with DeltaCode and provided on an "AS IS" BASIS, WITHOUT WARRANTIES
#  OR CONDITIONS OF ANY KIND, either express or implied. No content created from
#  DeltaCode should be considered or used as legal advice. Consult an Attorney
#  for any legal advice.
#  DeltaCode is a free and open source software analysis tool from nexB Inc. and others.
#  Visit https://github.com/nexB/deltacode/ for support and download.
#

from __future__ import absolute_import

from collections import OrderedDict

from deltacode.models import File
from deltacode.models import Scan
from deltacode import utils


from pkg_resources import get_distribution, DistributionNotFound
try:
    __version__ = get_distribution('deltacode').version
except DistributionNotFound:
    # package is not installed ??
    __version__ = '0.0.1.beta'


class DeltaCode(object):
    """
    Handle the basic operations on a pair of incoming ScanCode scans (in JSON
    format) and the Delta objects created from a comparison of the files (in
    the form of File objects) contained in those scans.
    """
    def __init__(self, new_path, old_path, options):
        self.new = Scan(new_path)
        self.old = Scan(old_path)
        self.options = options
        self.deltas = OrderedDict([
            ('added', []),
            ('removed', []),
            ('moved', []),
            ('modified', []),
            ('unmodified', [])
        ])

        if self.new.path != '' and self.old.path != '':
            self.determine_delta()
            self.determine_moved()

    def align_scan(self):
        """
        Seek to align the paths of a pair of files (File objects) in the pair
        of incoming scans so that the attributes and other characteristics of
        the files can be compared with one another.  Call utils.fix_trees(),
        which calls utils.align_trees().
        """
        try:
            utils.fix_trees(self.new.files, self.old.files)
        except utils.AlignmentException:
            for f in self.new.files:
                f.original_path = f.path
            for f in self.old.files:
                f.original_path = f.path

    def determine_delta(self):
        """
        Given new and old scans, return an OrderedDict of Delta objects grouping
        the objects under the keys 'added', 'modified', 'removed' or 'unmodified'.
        Return None if no File objects can be loaded from either scan.
        """
        # align scan and create our index
        self.align_scan()
        new_index = self.new.index_files()
        old_index = self.old.index_files()

        # gathering counts to ensure no files lost or missing from our 'deltas' set
        new_files_visited = 0
        old_files_visited = 0

        # perform the deltas
        for path, new_files in new_index.items():
            for new_file in new_files:
                new_files_visited += 1

                if new_file.type != 'file':
                    continue

                try:
                    delta_old_files = old_index[path]
                except KeyError:
                    self.deltas['added'].append(Delta(new_file, None, 'added'))
                    continue

                # at this point, we have a delta_old_file.
                # we need to determine wheather this is identical,
                # or a modification.
                for f in delta_old_files:
                    # TODO: make sure sha1 is NOT empty
                    if new_file.sha1 == f.sha1:
                        self.deltas['unmodified'].append(Delta(new_file, f, 'unmodified'))
                        continue
                    else:
                        delta = Delta(new_file, f, 'modified')
                        self.deltas['modified'].append(delta)

        # now time to find the added.
        for path, old_files in old_index.items():
            for old_file in old_files:
                old_files_visited += 1

                if old_file.type != 'file':
                    continue

                try:
                    # This file already classified as 'modified' or 'unmodified' so do nothing
                    new_index[path]
                except KeyError:
                    self.deltas['removed'].append(Delta(None, old_file, 'removed'))
                    continue

        # make sure everything is accounted for
        assert new_files_visited == self.new.files_count, "Number of visited files({})) does not match total_files({}) in the new scan".format(new_files_visited, self.new.files_count)
        assert old_files_visited == self.old.files_count, "Number of visited files({})) does not match total_files({}) in the old scan".format(old_files_visited, self.old.files_count)

    def determine_moved(self):
        """
        Modify the OrderedDict of Delta objects by creating an index of
        'removed' Delta objects and an index of 'added' Delta objects indexed
        by their 'sha1' attribute, identifying any unique pairs of Deltas in
        both indices with the same 'sha1' and File 'name' attributes, and
        converting each such pair of 'added' and 'removed' Delta objects to a
        'moved' Delta object.
        """
        added = self.index_deltas('sha1', [i for i in self.deltas['added']])
        removed = self.index_deltas('sha1', [i for i in self.deltas['removed']])

        # TODO: should it be iteritems() or items()
        for added_sha1, added_deltas in added.iteritems():
            for removed_sha1, removed_deltas in removed.iteritems():

                # check for matching sha1s on both sides
                if utils.check_moved(added_sha1, added_deltas, removed_sha1, removed_deltas):
                    self.update_deltas(added_deltas.pop(), removed_deltas.pop())

    def update_deltas(self, added, removed):
        """
        Convert the matched 'added' and 'removed' Delta objects to a combined
        'moved' Delta object and delete the 'added' and 'removed' objects.
        """
        self.deltas.get('moved').append(Delta(added.new_file, removed.old_file, 'moved'))
        self.deltas.get('added').remove(added)
        self.deltas.get('removed').remove(removed)

    def index_deltas(self, index_key='path', delta_list=[]):
        """
        Return a dictionary of a list of Delta objects indexed by the key
        passed via the 'index_key' variable.  If no 'index_key' variable is
        passed, the dict is keyed by the Delta object's 'path' variable.  For a
        'removed' Delta object, use the variable from the 'old_file'; for all
        other Delta objects (e.g., 'added'), use the 'new_file'.  This function
        does not currently catch the AttributeError exception.
        """
        index = {}

        for delta in delta_list:
            if delta.category == 'removed':
                key = getattr(delta.old_file, index_key)
            else:
                key = getattr(delta.new_file, index_key)

            if index.get(key) is None:
                index[key] = []
                index[key].append(delta)
            else:
                index[key].append(delta)

        return index

    def get_stats(self):
        """
        Given a list of Delta objects, return a 'counts' dictionary keyed by
        category -- i.e., the keys of the determine_delta() OrderedDict of
        Delta objects -- that contains the count as a value for each category.
        """
        added, modified, moved, removed, unmodified = 0, 0, 0, 0, 0

        added = len(self.deltas['added'])
        modified = len(self.deltas['modified'])
        moved = len(self.deltas['moved'])
        removed = len(self.deltas['removed'])
        unmodified = len(self.deltas['unmodified'])

        return OrderedDict([('added', added), ('modified', modified), ('moved', moved), ('removed', removed), ('unmodified', unmodified)])

    def to_dict(self):
        """
        Given an OrderedDict of Delta objects, return an OrderedDict of Delta
        objects grouping the objects under the keys 'added', 'removed', 'moved',
        'modified' or 'unmodified'.
        """
        return OrderedDict([
            ('added', [d.to_dict() for d in self.deltas.get('added')]),
            ('removed', [d.to_dict() for d in self.deltas.get('removed')]),
            ('moved', [d.to_dict() for d in self.deltas.get('moved')]),
            ('modified', [d.to_dict() for d in self.deltas.get('modified')]),
            ('unmodified', [d.to_dict() for d in self.deltas.get('unmodified')]),
        ])


class Delta(object):
    """
    A tuple reflecting a comparison of two files -- each of which is a File
    object -- and the category that characterizes the comparison:
    'added', 'modified', 'moved', 'removed' or 'unmodified'.
    """
    def __init__(self, new_file=None, old_file=None, delta_type=None):
        self.new_file = new_file if new_file else File()
        self.old_file = old_file if old_file else File()
        self.category = delta_type if delta_type else ''

        # If a license change is detected, and depending on the nature of that change,
        # change the Delta object's 'category' attribute from 'modified' to
        # 'license change', 'license info removed' or 'license info added'.
        if self.category == 'modified':
            self._license_diff()

    def _license_diff(self, cutoff_score=50):
        """
        Compare the license details for a pair of 'new' and 'old' File objects
        in a Delta object and change the Delta object's 'category' attribute to
        'license info removed', 'license info added' or 'license change' if
        there has been a license change and depending on the nature of that change.
        """
        new_licenses = self.new_file.licenses or []
        old_licenses = self.old_file.licenses or []

        if len(self.new_file.licenses) > 0 and self.old_file.licenses == []:
            self.category = 'license info added'
            return

        if self.new_file.licenses == [] and len(self.old_file.licenses) > 0:
            self.category = 'license info removed'
            return

        new_keys = set(l.key for l in new_licenses if l.score >= cutoff_score)
        old_keys = set(l.key for l in old_licenses if l.score >= cutoff_score)

        if new_keys != old_keys:
            self.category = 'license change'

    def to_dict(self):
        """
        Check the 'category' attribute of the Delta object and return an
        OrderedDict comprising the 'category' and 'path' of the object.
        """
        delta = OrderedDict([('category', self.category)])

        if self.category == 'added':
            delta.update(OrderedDict([
                ('new', self.new_file.to_dict()),
                ('old', None),
            ]))

        elif self.category == 'removed':
            delta.update(OrderedDict([
                ('new', None),
                ('old', self.old_file.to_dict()),
            ]))

        else:
            delta.update(OrderedDict([
                ('new', self.new_file.to_dict()),
                ('old', self.old_file.to_dict()),
            ]))

        return delta
