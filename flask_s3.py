import os
import logging
import hashlib
import json
from collections import defaultdict
import re

import boto3
import boto3.exceptions
from botocore.exceptions import ClientError
from flask import url_for as flask_url_for
from flask import current_app

logger = logging.getLogger('flask_s3')


import six

def merge_two_dicts(x, y):
    '''Given two dicts, merge them into a new dict as a shallow copy.'''
    z = x.copy()
    z.update(y)
    return z


def hash_file(filename):
    """
    Generate a hash for the contents of a file
    """
    hasher = hashlib.sha1()
    with open(filename, 'rb') as f:
        buf = f.read(65536)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(65536)

    return hasher.hexdigest()


def url_for(endpoint, **values):
    """
    Generates a URL to the given endpoint.

    If the endpoint is for a static resource then an Amazon S3 URL is
    generated, otherwise the call is passed on to `flask.url_for`.

    Because this function is set as a jinja environment variable when
    `FlaskS3.init_app` is invoked, this function replaces
    `flask.url_for` in templates automatically. It is unlikely that this
    function will need to be directly called from within your
    application code, unless you need to refer to static assets outside
    of your templates.
    """
    app = current_app
    if app.config.get('TESTING', False) and not app.config.get('S3_OVERRIDE_TESTING', True):
        return flask_url_for(endpoint, **values)
    if 'S3_BUCKET_NAME' not in app.config:
        raise ValueError("S3_BUCKET_NAME not found in app configuration.")

    if endpoint == 'static' or endpoint.endswith('.static'):
        scheme = 'https'
        if app.config['S3_USE_HTTP']:
            scheme = 'http'

        if app.config['S3_URL_STYLE'] == 'host':
            url_format = '%(bucket_name)s.%(bucket_domain)s'
        elif app.config['S3_URL_STYLE'] == 'path':
            url_format = '%(bucket_domain)s/%(bucket_name)s'
        else:
            raise ValueError('Invalid S3 URL style: "%s"'
                             % app.config['S3_URL_STYLE'])

        bucket_path = url_format % {
            'bucket_name': app.config['S3_BUCKET_NAME'],
            'bucket_domain': app.config['S3_BUCKET_DOMAIN'],
        }

        if app.config['S3_CDN_DOMAIN']:
            bucket_path = '%s' % app.config['S3_CDN_DOMAIN']
        urls = app.url_map.bind(bucket_path, url_scheme=scheme)
        return urls.build(endpoint, values=values, force_external=True)
    return flask_url_for(endpoint, **values)


def _bp_static_url(blueprint):
    """ builds the absolute url path for a blueprint's static folder """
    u = six.u('%s%s' % (blueprint.url_prefix or '', blueprint.static_url_path or ''))
    return u


def _gather_files(app, hidden):
    """ Gets all files in static folders and returns in dict."""
    dirs = [(six.u(app.static_folder), app.static_url_path)]
    if hasattr(app, 'blueprints'):
        blueprints = app.blueprints.values()
        bp_details = lambda x: (x.static_folder, _bp_static_url(x))
        dirs.extend([bp_details(x) for x in blueprints if x.static_folder])

    valid_files = defaultdict(list)
    for static_folder, static_url_loc in dirs:
        if not os.path.isdir(static_folder):
            logger.warning("WARNING - [%s does not exist]" % static_folder)
        else:
            logger.debug("Checking static folder: %s" % static_folder)
        for root, _, files in os.walk(static_folder):
            files = [os.path.join(root, x) \
                     for x in files if hidden or x[0] != '.']
            if files:
                valid_files[(static_folder, static_url_loc)].extend(files)
    return valid_files


def _path_to_relative_url(path):
    """ Converts a folder and filename into a ralative url path """
    return os.path.splitdrive(path)[1].replace('\\', '/')


def _static_folder_path(static_url, static_folder, static_asset):
    """
    Returns a path to a file based on the static folder, and not on the
    filesystem holding the file.

    Returns a path relative to static_url for static_asset
    """
    # first get the asset path relative to the static folder.
    # static_asset is not simply a filename because it could be
    # sub-directory then file etc.
    if not static_asset.startswith(static_folder):
        raise ValueError("%s static asset must be under %s static folder" %
                         (static_asset, static_folder))
    rel_asset = static_asset[len(static_folder):]
    # Now bolt the static url path and the relative asset location together
    return '%s/%s' % (static_url.rstrip('/'), rel_asset.lstrip('/'))


def _write_files(s3, app, static_url_loc, static_folder, files, bucket,
                 ex_keys=None, hashes=None):
    """ Writes all the files inside a static folder to S3. """
    new_hashes = []
    static_folder_rel = _path_to_relative_url(static_folder)
    for file_path in files:
        asset_loc = _path_to_relative_url(file_path)
        full_key_name = _static_folder_path(static_url_loc, static_folder_rel,
                                       asset_loc)
        key_name = full_key_name.lstrip("/")
        msg = "Uploading %s to %s as %s" % (file_path, bucket, key_name)
        logger.debug(msg)

        exclude = False
        if app.config.get('S3_ONLY_MODIFIED', False):
            file_hash = hash_file(file_path)
            new_hashes.append((full_key_name, file_hash))

            if hashes and hashes.get(full_key_name, None) == file_hash:
                exclude = True

        if ex_keys and full_key_name in ex_keys or exclude:
            logger.debug("%s excluded from upload" % key_name)
        else:
            h = {}
            # Set more custom headers if the filepath matches certain
            # configured regular expressions.
            filepath_headers = app.config.get('S3_FILEPATH_HEADERS')
            if filepath_headers:
                for filepath_regex, headers in filepath_headers.iteritems():
                    if re.search(filepath_regex, file_path):
                        for header, value in headers.iteritems():
                            h[header] = value

            with open(file_path) as fp:
                s3.put_object(Bucket=bucket,
                              Key=key_name,
                              Body=fp.read(),
                              ACL="public-read",
                              Metadata=merge_two_dicts(app.config['S3_HEADERS'], h))




    return new_hashes


def _upload_files(s3, app, files_, bucket, hashes=None):
    new_hashes = []
    for (static_folder, static_url), names in six.iteritems(files_):
        new_hashes.extend(_write_files(s3, app, static_url, static_folder, names,
                                       bucket, hashes=hashes))
    return new_hashes


def create_all(app, user=None, password=None, bucket_name=None,
               location=None, include_hidden=False):
    """
    Uploads of the static assets associated with a Flask application to
    Amazon S3.

    All static assets are identified on the local filesystem, including
    any static assets associated with *registered* blueprints. In turn,
    each asset is uploaded to the bucket described by `bucket_name`. If
    the bucket does not exist then it is created.

    Flask-S3 creates the same relative static asset folder structure on
    S3 as can be found within your Flask application.

    Many of the optional arguments to `create_all` can be specified
    instead in your application's configuration using the Flask-S3
    `configuration`_ variables.

    :param app: a :class:`flask.Flask` application object.

    :param user: an AWS Access Key ID. You can find this key in the
                 Security Credentials section of your AWS account.
    :type user: `basestring` or None

    :param password: an AWS Secret Access Key. You can find this key in
                     the Security Credentials section of your AWS
                     account.
    :type password: `basestring` or None

    :param bucket_name: the name of the bucket you wish to server your
                        static assets from. **Note**: while a valid
                        character, it is recommended that you do not
                        include periods in bucket_name if you wish to
                        serve over HTTPS. See Amazon's `bucket
                        restrictions`_ for more details.
    :type bucket_name: `basestring` or None

    :param location: the AWS region to host the bucket in; an empty
                     string indicates the default region should be used,
                     which is the US Standard region. Possible location
                     values include: `'DEFAULT'`, `'EU'`, `'USWest'`,
                     `'APSoutheast'`
    :type location: `basestring` or None

    :param include_hidden: by default Flask-S3 will not upload hidden
        files. Set this to true to force the upload of hidden files.
    :type include_hidden: `bool`

    .. _bucket restrictions: http://docs.amazonwebservices.com/AmazonS3\
    /latest/dev/BucketRestrictions.html

    """
    user = user or app.config.get('AWS_ACCESS_KEY_ID')
    password = password or app.config.get('AWS_SECRET_ACCESS_KEY')
    bucket_name = bucket_name or app.config.get('S3_BUCKET_NAME')
    if not bucket_name:
        raise ValueError("No bucket name provided.")
    location = location or app.config.get('S3_REGION')

    # build list of static files
    all_files = _gather_files(app, include_hidden)
    logger.debug("All valid files: %s" % all_files)

    # connect to s3
    s3 = boto3.client("s3",
                      region_name=location or None,
                      aws_access_key_id=user,
                      aws_secret_access_key=password)

    # get_or_create bucket
    try:
        s3.head_bucket(Bucket=bucket_name)
    except ClientError as e:
        if int(e.response['Error']['Code']) == 404:
            # Create the bucket
            bucket = s3.create_bucket(Bucket=bucket_name)
        else:
            raise

    s3.put_bucket_acl(Bucket=bucket_name, ACL='public-read')

    if app.config['S3_ONLY_MODIFIED']:
        try:
            hashes_object = s3.get_object(Bucket=bucket_name, Key='.file-hashes')
            hashes = json.loads(str(hashes_object['Body'].read()))
        except ClientError as e:
            logger.warn("No file hashes found: %s" % e)
            hashes = None

        new_hashes = _upload_files(s3, app, all_files, bucket_name, hashes=hashes)

        try:
            s3.put_object(Bucket=bucket_name,
                          Key='.file-hashes',
                          Body=json.dumps(dict(new_hashes)),
                          ACL='private')
        except boto3.exceptions.S3UploadFailedError as e:
            logger.warn("Unable to upload file hashes: %s" % e)
    else:
        _upload_files(s3, app, all_files, bucket_name)


class FlaskS3(object):
    """
    The FlaskS3 object allows your application to use Flask-S3.

    When initialising a FlaskS3 object you may optionally provide your
    :class:`flask.Flask` application object if it is ready. Otherwise,
    you may provide it later by using the :meth:`init_app` method.

    :param app: optional :class:`flask.Flask` application object
    :type app: :class:`flask.Flask` or None
    """

    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """
        An alternative way to pass your :class:`flask.Flask` application
        object to Flask-S3. :meth:`init_app` also takes care of some
        default `settings`_.

        :param app: the :class:`flask.Flask` application object.
        """
        defaults = [('S3_USE_HTTP', False),
                    ('USE_S3', True),
                    ('USE_S3_DEBUG', False),
                    ('S3_BUCKET_DOMAIN', 's3.amazonaws.com'),
                    ('S3_CDN_DOMAIN', ''),
                    ('S3_USE_CACHE_CONTROL', False),
                    ('S3_HEADERS', {}),
                    ('S3_FILEPATH_HEADERS', {}),
                    ('S3_ONLY_MODIFIED', False),
                    ('S3_URL_STYLE', 'host')]

        for k, v in defaults:
            app.config.setdefault(k, v)

        if app.debug and not app.config['USE_S3_DEBUG']:
            app.config['USE_S3'] = False

        if app.config['USE_S3']:
            app.jinja_env.globals['url_for'] = url_for
        if app.config['S3_USE_CACHE_CONTROL'] and app.config.get('S3_CACHE_CONTROL'):
            cache_control_header = app.config['S3_CACHE_CONTROL']
            app.config['S3_HEADERS']['Cache-Control'] = cache_control_header
