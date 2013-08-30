#!/usr/bin/env python
# Copyright 2013 Kevin Ran
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Utility for image set diffs.

 - Given two endpoints, cURL POSTs to them and attempts to gather all URLs from the responses.
 - Basenames of the URLs are assumed to be the image names.
 - The Image names will be matched to each other and pairs will be created.
 - Diffs happen wooo
"""

import HTMLParser
import Queue
import datetime
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import urlparse
import urllib
import collections

from urllib2 import Request, urlopen

# Flags & custom flags
import gflags
FLAGS = gflags.FLAGS

gflags.DEFINE_string(
    'old_endpoint', None,
    'Base endpoint that returns image urls to compare.')

gflags.DEFINE_string(
    'new_endpoint', None,
    'New endpoint that returns image urls to compare with those in --base_folder.')

gflags.DEFINE_string(
    'json_path', None,
    'Path to iteratively use when parsing URLs from endpoint JSON')

gflags.DEFINE_string(
    'url_prepend_old', None,
    'String to append to URLs in paths returned by the --old_endpoint')

gflags.DEFINE_string(
    'url_prepend_new', None,
    'String to append to URLs in paths returned by the --new_endpoint')

gflags.DEFINE_string(
    'run_name_depth', None,
    'URLs for the images may be large. This can shorten them for yous.')

# Local modules
from dpxdt.client import fetch_worker
from dpxdt.client import release_worker
from dpxdt.client import workers
import flags

# local classes
from dpxdt.classes.PrintWorkflow import PrintWorkflow


class PrintWorkflow(workers.WorkflowItem):
    """Prints a message to stdout."""

    def run(self, message):
        yield []  # Make this into a generator
        print message



class UrlPairSetDiff(workers.WorkflowItem):
    """
    Workflow for diffing a set of URL pairs to a single release

    Args:
        image_pairs: tuple pairs of image urls (old_img => new_img) to diff
        upload_build_id: Optional. Build ID of the site being compared. When
            supplied a new release will be cut for this build comparing it
            to the last good release.
        upload_release_name: Optional. Release name to use for the build. When
            not supplied, a new release based on the current time will be
            created.
        heartbeat: Function to call with progress status.
    """

    def run(self,
            image_pairs,
            upload_build_id,
            upload_release_name=None,
            heartbeat=None,
            run_name_depth=2):

        if not upload_release_name:
            upload_release_name = str(datetime.datetime.utcnow())

        yield heartbeat('Creating release %s' % upload_release_name)
        release_number = yield release_worker.CreateReleaseWorkflow(
            upload_build_id, upload_release_name, upload_release_name)

        config_dict = {
            'viewportSize': {
                'width': 1280,
                'height': 1024,
            }
        }
        if FLAGS.inject_css:
            config_dict['injectCss'] = FLAGS.inject_css
        if FLAGS.inject_js:
            config_dict['injectJs'] = FLAGS.inject_js
        config_data = json.dumps(config_dict)

        yield heartbeat('Requesting captures')
        requests = []
        for old_img, new_img in image_pairs.iteritems():

            yield heartbeat( old_img )
            yield heartbeat( new_img )
            yield heartbeat( '--------------------------------' )

            url_parts = urlparse.urlparse(new_img)
            url       = ( url_parts.path or '/' ).split( '/' )
            run_name  = url.pop()
            for depth in range( run_name_depth-1 ):
              run_name = url.pop() + '/' + run_name
              if len( url ) <= 0:
                break
            run_name = urllib.url2pathname( run_name )

            requests.append(
              release_worker.RequestRunWorkflow(
                upload_build_id,
                upload_release_name,
                release_number,
                run_name,
                new_img,
                config_data,
                ref_url=old_img,
                ref_config_data=config_data
              )
            )

        yield heartbeat('Processing requests ...')
        yield requests

        yield heartbeat('Marking runs as complete')
        release_url = yield release_worker.RunsDoneWorkflow(
            upload_build_id, upload_release_name, release_number)

        yield heartbeat('Results viewable at: %s' % release_url)


def get_url( endpoint=None ):
  """GETs a given endpoint, returns the JSON"""
  if endpoint is not None:
    return urlopen( Request( url=endpoint ) ).read()
  # todo: care
  sys.exit( 'Failed to GET: [' + endpoint + ']' )


def parse_urls( json_str='', json_path='', url_append='' ):

  """Attempt to parse out a list of URLs from an object"""

  json_path = str( json_path )
  path      = json_path.split( ',' )
  data_key  = path.pop().strip()
  data      = json.loads( json_str )
  ret       = []

  # traverse down to a list of objects
  if path is not None and len( path ) is not 0:
    for index in path:
      try:
        data = data[ index ]
      except IndexError:
        sys.exit( 'Invalid JSON path given: [%s] in %s'
                  % (index, json_path) )

  # pull out data
  # todo: make the data key path a bit more flexible
  if len( data_key ) is 0 or data_key is None:
    ret = data
  else:
    for obj in data:
      try:
        url = urllib.pathname2url( obj[ data_key ] )
        ret.append( url_append + url )
      except TypeError:
        sys.exit( 'FATAL: [%s] in %s does not yield any URLs' % (data_key, json_path) )

  ret.sort()
  return ret


def map_urls(base_urls=[],
             new_urls=[]):

  """
  Creates URL pairs based on basename.
  Any images that cannot be matched will be thrown in buckets
  """

  new   = {}
  old   = {}
  pairs = {}

  for new_url in new_urls:

    image_name = os.path.basename( new_url )
    matches    = filter( lambda img: re.search( image_name, img ), base_urls )
    matches    = collections.deque( matches )

    if len( matches ) == 0:
      print "New image: %s" % image_name
      new[ new_url ] = 'about:blank'
      continue

    # always use the first image found
    old_url          = matches.popleft()
    pairs[ new_url ] = old_url

    del base_urls[ base_urls.index( old_url ) ]

    if len( matches ) >= 1:
      print "Warning: %s matched multiple images!" % image_name
      print matches

  # merge results
  # safe to use ** since all keys are strings
  pairs = dict( pairs, **new );

  # sort old images
  old   = { ( base_urls[ index ], 'about:blank' ) for index in range( 0, len( base_urls ) ) }

  # finally, create store object
  store          = {}
  store['old']   = old
  store['pairs'] = dict( ( n, pairs[n] ) for n in sorted( pairs.keys() ) )

  return store


def real_main(upload_build_id=None,
              upload_release_name=None,
              old_endpoint=None,
              new_endpoint=None,
              path='',
              prepend_old='',
              prepend_new='',
              run_name_depth=2):

    """Runs pair diffs between URL pairs in the given config file"""

    print "Gathering URLs from %s" % old_endpoint
    old_images = parse_urls(json_str=get_url(old_endpoint),
                            json_path=path,
                            url_append=prepend_old)

    print "Gathering URLs from %s" % new_endpoint
    new_images = parse_urls(json_str=get_url(new_endpoint),
                            json_path=path,
                            url_append=prepend_new)

    print 'Pairing images ...'
    data = map_urls(base_urls=old_images,
                    new_urls=new_images)

    coordinator = workers.get_coordinator()
    fetch_worker.register(coordinator)
    coordinator.start()

    item = UrlPairSetDiff(
        image_pairs=data['pairs'],
        upload_build_id=upload_build_id,
        upload_release_name=upload_release_name,
        heartbeat=PrintWorkflow,
        run_name_depth=run_name_depth)
    item.root = True

    coordinator.input_queue.put(item)
    coordinator.wait_one()


def main(argv):

    try:
        argv = FLAGS(argv)
    except gflags.FlagsError, e:
        print '%s\nUsage: %s ARGS\n%s' % (e, sys.argv[0], FLAGS)
        sys.exit(1)

    assert FLAGS.upload_build_id
    assert FLAGS.release_server_prefix
    assert FLAGS.old_endpoint
    assert FLAGS.new_endpoint

    # required; don't want to pollute other releases
    assert FLAGS.upload_release_name

    if FLAGS.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    real_main(
        upload_build_id=FLAGS.upload_build_id,
        upload_release_name=FLAGS.upload_release_name,
        old_endpoint=FLAGS.old_endpoint,
        new_endpoint=FLAGS.new_endpoint,
        path=str( FLAGS.json_path ),
        prepend_old=str( FLAGS.url_prepend_old ),
        prepend_new=str( FLAGS.url_prepend_new ),
        run_name_depth=FLAGS.run_name_depth or 2)


if __name__ == '__main__':
    main(sys.argv)
