import io
import os
import re
import gzip
import json
import hashlib
import logging
import mimetypes

from collections import defaultdict


import boto3
import boto3.exceptions
from botocore.exceptions import ClientError

from tqdm import tqdm
from flask import current_app
from flask import url_for as flask_url_for

logger = logging.getLogger('flask_s3')

# Mapping for Header names to S3 parameters
header_mapping = {
    'cache-control': 'CacheControl',
    'content-disposition': 'ContentDisposition',
    'content-encoding': 'ContentEncoding',
    'content-language': 'ContentLanguage',
    'content-length': 'ContentLength',
    'content-md5': 'ContentMD5',
    'content-type': 'ContentType',
    'expires': 'Expires',
}

DEFAULT_SETTINGS = {'FLASKS3_USE_HTTPS': True,
                    'FLASKS3_ACTIVE': True,
                    'FLASKS3_DEBUG': False,
                    'FLASKS3_BUCKET_DOMAIN': 's3.amazonaws.com',
                    'FLASKS3_CDN_DOMAIN': '',
                    'FLASKS3_USE_CACHE_CONTROL': False,
                    'FLASKS3_HEADERS': {},
                    'FLASKS3_FILEPATH_HEADERS': {},
                    'FLASKS3_ONLY_MODIFIED': False,
                    'FLASKS3_URL_STYLE': 'host',
                    'FLASKS3_ENDPOINT_URL': None,
                    'FLASKS3_GZIP': False,
                    'FLASKS3_GZIP_ONLY_EXTS': [],
                    'FLASKS3_FORCE_MIMETYPE': False,
                    'FLASKS3_PREFIX': ''}


def _get_statics_prefix(app):
    """
    Get the complete prefix that should be used by static files.
    """
    upload_prefix = app.config.get('FLASKS3_PREFIX', '')
    return '/%s' % upload_prefix.lstrip('/').rstrip('/')


def split_metadata_params(headers):
    """
    Given a dict of headers for s3, seperates those that are boto3
    parameters and those that must be metadata
    """

    params = {}
    metadata = {}
    for header_name in headers:
        if header_name.lower() in header_mapping:
            params[header_mapping[header_name.lower()]] = headers[header_name]
        else:
            metadata[header_name] = headers[header_name]
    return metadata, params


def merge_two_dicts(x, y):
    """Given two dicts, merge them into a new dict as a shallow copy."""
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


def _get_bucket_name(**values):
    """
    Generates the bucket name for url_for.
    """
    app = current_app
    # manage other special values, all have no meaning for static urls
    values.pop('_external', False)  # external has no meaning here
    values.pop('_anchor', None)  # anchor as well
    values.pop('_method', None)  # method too

    url_style = get_setting('FLASKS3_URL_STYLE', app)
    if url_style == 'host':
        url_format = '{bucket_name}.{bucket_domain}'
    elif url_style == 'path':
        url_format = '{bucket_domain}/{bucket_name}'
    else:
        raise ValueError('Invalid S3 URL style: "{}"'.format(url_style))

    if get_setting('FLASKS3_CDN_DOMAIN', app):
        bucket_path = '{}'.format(get_setting('FLASKS3_CDN_DOMAIN', app))

    else:
        bucket_path = url_format.format(
            bucket_name=get_setting('FLASKS3_BUCKET_NAME', app),
            bucket_domain=get_setting('FLASKS3_BUCKET_DOMAIN', app),
        )

    bucket_path += _get_statics_prefix(app).rstrip('/')

    return bucket_path, values


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
    if app.config.get('TESTING', False) and not app.config.get('FLASKS3_OVERRIDE_TESTING', True):
        return flask_url_for(endpoint, **values)
    if 'FLASKS3_BUCKET_NAME' not in app.config:
        raise ValueError("FLASKS3_BUCKET_NAME not found in app configuration.")

    if endpoint == 'static' or endpoint.endswith('.static'):
        scheme = 'https'
        if not app.config.get("FLASKS3_USE_HTTPS", True):
            scheme = 'http'

        # allow per url override for scheme
        scheme = values.pop('_scheme', scheme)

        bucket_path, values = _get_bucket_name(**values)

        urls = app.url_map.bind(bucket_path, url_scheme=scheme)
        built = urls.build(endpoint, values=values, force_external=True)
        return built
    return flask_url_for(endpoint, **values)


def _bp_static_url(blueprint) -> str:
    """ builds the absolute url path for a blueprint's static folder """
    return f"{blueprint.url_prefix or ''}{blueprint.static_url_path or ''}"

def _gather_files(app, hidden, filepath_filter_regex=None):
    """ Gets all files in static folders and returns in dict."""
    dirs = [(app.static_folder, app.static_url_path)]
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
            relative_folder = re.sub(r'^/',
                                     '',
                                     root.replace(static_folder, ''))

            files = [os.path.join(root, x)
                     for x in files if (
                         (hidden or x[0] != '.') and
                         # Skip this file if the filter regex is
                         # defined, and this file's path is a
                         # negative match.
                         (filepath_filter_regex == None or re.search(
                             filepath_filter_regex,
                             os.path.join(relative_folder, x))))]
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
    should_gzip = app.config.get('FLASKS3_GZIP')
    add_mime = app.config.get('FLASKS3_FORCE_MIMETYPE')
    gzip_include_only = app.config.get('FLASKS3_GZIP_ONLY_EXTS')
    new_hashes = []
    static_folder_rel = _path_to_relative_url(static_folder)
    for file_path in tqdm(files, desc="Uploading: {}".format(static_folder)):
        per_file_should_gzip = should_gzip
        asset_loc = _path_to_relative_url(file_path)
        full_key_name = _static_folder_path(static_url_loc, static_folder_rel,
                                            asset_loc)
        key_name = full_key_name.lstrip("/")
        logger.debug("Uploading {} to {} as {}".format(file_path, bucket, key_name))

        exclude = False
        if app.config.get('FLASKS3_ONLY_MODIFIED', False):
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
            filepath_headers = app.config.get('FLASKS3_FILEPATH_HEADERS')
            if filepath_headers:
                for filepath_regex, headers in filepath_headers.items():
                    if re.search(filepath_regex, file_path):
                        for header, value in headers.items():
                            h[header] = value

            # check for extension, only if there are extensions provided
            if per_file_should_gzip and gzip_include_only:
                if os.path.splitext(file_path)[1] not in gzip_include_only:
                    per_file_should_gzip = False

            if per_file_should_gzip:
                h["content-encoding"] = "gzip"

            if (add_mime or per_file_should_gzip) and "content-type" not in h:
                # When we use GZIP we have to explicitly set the content type
                # or if the mime flag is True
                (mimetype, encoding) = mimetypes.guess_type(file_path,
                                                            False)
                if mimetype:
                    h["content-type"] = mimetype
                else:
                    logger.warn("Unable to detect mimetype for %s" %
                                file_path)

            with open(file_path, 'rb') as fp:
                merged_dicts = merge_two_dicts(get_setting('FLASKS3_HEADERS', app), h)
                metadata, params = split_metadata_params(merged_dicts)
                if per_file_should_gzip:
                    compressed = io.BytesIO()
                    z = gzip.GzipFile(os.path.basename(file_path), 'wb', 9,
                                      compressed)
                    z.write(fp.read())
                    z.close()

                    data = compressed.getvalue()
                else:
                    data = fp.read()

                s3.put_object(Bucket=bucket,
                              Key=key_name,
                              Body=data,
                              ACL="public-read",
                              Metadata=metadata,
                              **params)

    return new_hashes


def _upload_files(s3, app, files_, bucket, hashes=None):
    new_hashes = []
    prefix = _get_statics_prefix(app)
    for (static_folder, static_url), names in files_.items():
        static_upload_url = '%s/%s' % (prefix.rstrip('/'), static_url.lstrip('/'))
        new_hashes.extend(_write_files(s3, app, static_upload_url, static_folder,
                                       names, bucket, hashes=hashes))
    return new_hashes


def get_setting(name, app=None):
    """
    Returns the value for `name` settings (looks into `app` config, and into
    DEFAULT_SETTINGS). Returns None if not set.

    :param name: (str) name of a setting (e.g. FLASKS3_URL_STYLE)

    :param app: Flask app instance

    :return: setting value or None
    """
    default_value = DEFAULT_SETTINGS.get(name, None)
    return app.config.get(name, default_value) if app else default_value


def create_all(app, user=None, password=None, bucket_name=None,
               location=None, include_hidden=False,
               filepath_filter_regex=None, put_bucket_acl=True):
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
                     values include: `'DEFAULT'`, `'EU'`, `'us-east-1'`,
                     `'us-west-1'`, `'us-west-2'`, `'ap-south-1'`,
                     `'ap-northeast-2'`, `'ap-southeast-1'`,
                     `'ap-southeast-2'`, `'ap-northeast-1'`,
                     `'eu-central-1'`, `'eu-west-1'`,  `'sa-east-1'`
    :type location: `basestring` or None

    :param include_hidden: by default Flask-S3 will not upload hidden
        files. Set this to true to force the upload of hidden files.
    :type include_hidden: `bool`

    :param filepath_filter_regex: if specified, then the upload of
        static assets is limited to only those files whose relative path
        matches this regular expression string. For example, to only
        upload files within the 'css' directory of your app's static
        store, set to r'^css'.
    :type filepath_filter_regex: `basestring` or None

    :param put_bucket_acl: by default Flask-S3 will set the bucket ACL
        to public. Set this to false to leave the policy unchanged.
    :type put_bucket_acl: `bool`

    .. _bucket restrictions: http://docs.amazonwebservices.com/AmazonS3\
    /latest/dev/BucketRestrictions.html

    """
    user = user or app.config.get('AWS_ACCESS_KEY_ID')
    password = password or app.config.get('AWS_SECRET_ACCESS_KEY')

    if not user:
        raise ValueError("you must set 'user' or 'AWS_ACCESS_KEY_ID'")

    if not password:
        raise ValueError("you must set 'password' or 'AWS_SECRET_ACCESS_KEY'")

    bucket_name = bucket_name or app.config.get('FLASKS3_BUCKET_NAME')
    if not bucket_name:
        raise ValueError("No bucket name provided.")
    location = location or app.config.get('FLASKS3_REGION')
    endpoint_url = app.config.get('FLASKS3_ENDPOINT_URL')

    # build list of static files
    all_files = _gather_files(app, include_hidden,
                              filepath_filter_regex=filepath_filter_regex)
    logger.debug("All valid files: %s" % all_files)

    # connect to s3
    s3 = boto3.client("s3",
                      endpoint_url=endpoint_url,
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

    if put_bucket_acl:
        s3.put_bucket_acl(Bucket=bucket_name, ACL='public-read')

    if get_setting('FLASKS3_ONLY_MODIFIED', app):
        try:
            hashes_object = s3.get_object(Bucket=bucket_name, Key='.file-hashes')
            hashes = json.loads(str(hashes_object['Body'].read().decode()))
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

        for k, v in DEFAULT_SETTINGS.items():
            app.config.setdefault(k, v)

        if app.debug and not get_setting('FLASKS3_DEBUG', app):
            app.config['FLASKS3_ACTIVE'] = False

        if get_setting('FLASKS3_ACTIVE', app):
            app.jinja_env.globals['url_for'] = url_for
        if get_setting('FLASKS3_USE_CACHE_CONTROL', app) and app.config.get('FLASKS3_CACHE_CONTROL'):
            cache_control_header = get_setting('FLASKS3_CACHE_CONTROL', app)
            app.config['FLASKS3_HEADERS']['Cache-Control'] = cache_control_header
