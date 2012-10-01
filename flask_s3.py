import os
import logging
from collections import defaultdict

from flask import url_for as flask_url_for
from flask import current_app
from boto.s3.connection import S3Connection
from boto.exception import S3CreateError
from boto.s3.key import Key


logger = logging.getLogger('flask_s3')
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
logger.addHandler(ch)

def url_for(endpoint, **values):
    """
    If the endpoint is for static resources then create a new MapAdapter based 
    upon the application's url map, but forcing the use of an external server 
    name. 
    """
    app = current_app
    if 'S3_BUCKET_NAME' not in app.config:
        raise ValueError("S3_BUCKET_NAME not found in app configuration.")

    if endpoint == 'static' or endpoint.endswith('.static'):
        scheme = 'http'
        if app.config['S3_USE_HTTPS']:
            scheme = 'https'
        bucket_path = '%s.%s' % (app.config['S3_BUCKET_NAME'], 
                                 app.config['S3_BUCKET_DOMAIN'])
        urls = app.url_map.bind(bucket_path, url_scheme=scheme)
        return urls.build(endpoint, values=values, force_external=True)
    return flask_url_for(endpoint, **values)


def _bp_static_url(blueprint):
    """ builds the absolute url path for a blueprint's static folder """
    return u'%s%s' % (blueprint.url_prefix or '', blueprint.static_url_path)


def _gather_files(app, hidden):
    """ Gets all files in static folders and returns in dict."""
    dirs = [(unicode(app.static_folder), app.static_url_path)]
    if hasattr(app, 'blueprints'):
        bp_details = lambda x: (x.static_folder, _bp_static_url(x))
        dirs.extend([bp_details(x) for x in app.blueprints.values()])
        
    valid_files = defaultdict(list)
    for static_folder, static_url_loc  in dirs:
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

    returns a path relative to static_url for static_asset
    """
    # first get the asset path relative to the static folder. static_asset is
    # not simply a filename because it could be sub-directory then file etc.
    if not static_asset.startswith(static_folder):
        raise ValueError("%s startic asset must be under %s static folder" %
                         (static_asset, static_folder))
    rel_asset = static_asset[len(static_folder):]
    # Now bolt the static url path and the relative asset location together
    return u'%s/%s' % (static_url.rstrip('/'), rel_asset.lstrip('/'))


def _write_files(static_url_loc, static_folder, files, bucket, ex_keys=None):
    """ 
    Writes all the files inside a static folder to S3.
    """
    for file_path in files:
        asset_loc = _path_to_relative_url(file_path)
        key_name = _static_folder_path(static_url_loc, static_folder, asset_loc)
        logger.debug("[DEBUG] Uploading %s to %s as %s" % 
                                                (file_path, bucket, key_name))
        if ex_keys and key_name in ex_keys:
            logger.debug("[DEBUG] %s excluded from upload" % key_name)
        else:
            k = Key(bucket=bucket, name=key_name)
            k.set_contents_from_filename(file_path)
            k.make_public()


def _upload_files(files_, bucket):
    for (static_folder, static_url), names in files_.iteritems():
        _write_files(static_url, static_folder, names, bucket)


def create_all(app, user=None, password=None, bucket_name=None, 
               location='', overwrite=False, include_hidden=False):
    """
    Sends all static assets to S3.
    """
    if user is None and 'AWS_ACCESS_KEY_ID' in app.config:
        user = app.config['AWS_ACCESS_KEY_ID']
    if password is None and 'AWS_SECRET_ACCESS_KEY' in app.config:
        password = app.config['AWS_SECRET_ACCESS_KEY']
    if bucket_name is None and 'S3_BUCKET_NAME' in app.config:
        bucket_name = app.config['S3_BUCKET_NAME']
    if not bucket_name:
        raise ValueError("No bucket name provided.")
    # build list of static files
    all_files = _gather_files(app, include_hidden)
    logger.debug("All valid files: %s" % all_files)
    # connect to s3
    conn = S3Connection(user, password)
    # get_or_create bucket
    try:
        bucket = conn.create_bucket(bucket_name, location=location)
        bucket.make_public(recursive=True)
    except S3CreateError as e:
        raise e
    _upload_files(all_files, bucket)



class FlaskS3(object):
    """docstring for FlaskS3"""
    def __init__(self, app=None):
        self.app = None
        if app is not None:
            self.app = app
            self.init_app(self.app)

    def init_app(self, app):
        defaults = [('S3_USE_HTTPS', True), 
                    ('USE_S3', True), 
                    ('S3_DEBUG_FORCE', False),
                    ('S3_BUCKET_DOMAIN', 's3.amazonaws.com')]
        for k, v in defaults:
            app.config.setdefault(k, v)
        if app.config['USE_S3']:
            app.jinja_env.globals['url_for'] = url_for

