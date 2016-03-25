import ntpath
import os
import sys
import tempfile
import unittest

try:
    from unittest.mock import Mock, patch, call, mock_open
except ImportError:
    from mock import Mock, patch, call, mock_open
from flask import Flask, render_template_string, Blueprint
import six
import flask_s3
from flask_s3 import FlaskS3


class FlaskStaticTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.testing = True

        @self.app.route('/<url_for_string>')
        def a(url_for_string):
            return render_template_string(url_for_string)

    def test_jinja_url_for(self):
        """ Tests that the jinja global gets assigned correctly. """
        self.assertNotEqual(self.app.jinja_env.globals['url_for'],
                            flask_s3.url_for)
        # then we initialise the extension
        FlaskS3(self.app)
        self.assertEquals(self.app.jinja_env.globals['url_for'],
                          flask_s3.url_for)

    # Temporarily commented out
    """
    def test_config(self):
        "" Tests configuration vars exist. ""
        FlaskS3(self.app)
        defaults = ('S3_USE_HTTP', 'USE_S3', 'USE_S3_DEBUG',
                    'S3_BUCKET_DOMAIN', 'S3_CDN_DOMAIN',
                    'S3_USE_CACHE_CONTROL', 'S3_HEADERS',
                    'S3_URL_STYLE')
        for default in defaults:
            self.assertIn(default, self.app.config)
    """


class UrlTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.testing = True
        self.app.config['FLASKS3_BUCKET_NAME'] = 'foo'
        self.app.config['FLASKS3_USE_HTTPS'] = True
        self.app.config['FLASKS3_BUCKET_DOMAIN'] = 's3.amazonaws.com'
        self.app.config['FLASKS3_CDN_DOMAIN'] = ''
        self.app.config['FLASKS3_OVERRIDE_TESTING'] = True

        @self.app.route('/<url_for_string>')
        def a(url_for_string):
            return render_template_string(url_for_string)

        @self.app.route('/')
        def b():
            return render_template_string("{{url_for('b')}}")

        bp = Blueprint('admin', __name__, static_folder='admin-static')

        @bp.route('/<url_for_string>')
        def c():
            return render_template_string("{{url_for('b')}}")

        self.app.register_blueprint(bp)

    def client_get(self, ufs):
        FlaskS3(self.app)
        client = self.app.test_client()
        import six
        if six.PY3:
            return client.get('/%s' % ufs)
        elif six.PY2:
            return client.get('/{}'.format(ufs))

    def test_required_config(self):
        """
        Tests that ValueError raised if bucket address not provided.
        """
        raises = False

        del self.app.config['FLASKS3_BUCKET_NAME']

        try:
            ufs = "{{url_for('static', filename='bah.js')}}"
            self.client_get(ufs)
        except ValueError:
            raises = True
        self.assertTrue(raises)

    def test_url_for(self):
        """
        Tests that correct url formed for static asset in self.app.
        """
        # non static endpoint url_for in template
        self.assertEquals(self.client_get('').data, six.b('/'))
        # static endpoint url_for in template
        ufs = "{{url_for('static', filename='bah.js')}}"
        exp = 'https://foo.s3.amazonaws.com/static/bah.js'
        self.assertEquals(self.client_get(ufs).data, six.b(exp))

    def test_url_for_per_url_scheme(self):
        """
        Tests that if _scheme is passed in the url_for arguments, that
        scheme is used instead of configuration scheme.
        """
        # check _scheme overriden per url
        ufs = "{{url_for('static', filename='bah.js', _scheme='http')}}"
        exp = 'http://foo.s3.amazonaws.com/static/bah.js'
        self.assertEquals(self.client_get(ufs).data, six.b(exp))

    def test_url_for_handles_special_args(self):
        """
        Tests that if any special arguments are passed, they are ignored, and
        removed from generated url. As of this writing these are the special
        args: _external, _anchor, _method (from flask's url_for)
        """
        # check _external, _anchor, and _method are ignored, and not added
        # to the url
        ufs = "{{url_for('static', filename='bah.js',\
            _external=True, _anchor='foobar', _method='GET')}}"
        exp = 'https://foo.s3.amazonaws.com/static/bah.js'
        self.assertEquals(self.client_get(ufs).data, six.b(exp))

    def test_url_for_debug(self):
        """Tests Flask-S3 behaviour in debug mode."""
        self.app.debug = True
        # static endpoint url_for in template
        ufs = "{{url_for('static', filename='bah.js')}}"
        exp = '/static/bah.js'
        self.assertEquals(self.client_get(ufs).data, six.b(exp))

    def test_url_for_debug_override(self):
        """Tests Flask-S3 behavior in debug mode with USE_S3_DEBUG turned on."""
        self.app.debug = True
        self.app.config['FLASKS3_DEBUG'] = True
        ufs = "{{url_for('static', filename='bah.js')}}"
        exp = 'https://foo.s3.amazonaws.com/static/bah.js'
        self.assertEquals(self.client_get(ufs).data, six.b(exp))

    def test_url_for_blueprint(self):
        """
        Tests that correct url formed for static asset in blueprint.
        """
        # static endpoint url_for in template
        ufs = "{{url_for('admin.static', filename='bah.js')}}"
        exp = 'https://foo.s3.amazonaws.com/admin-static/bah.js'
        self.assertEquals(self.client_get(ufs).data, six.b(exp))

    def test_url_for_cdn_domain(self):
        self.app.config['FLASKS3_CDN_DOMAIN'] = 'foo.cloudfront.net'
        ufs = "{{url_for('static', filename='bah.js')}}"
        exp = 'https://foo.cloudfront.net/static/bah.js'
        self.assertEquals(self.client_get(ufs).data, six.b(exp))

    def test_url_for_url_style_path(self):
        """Tests that the URL returned uses the path style."""
        self.app.config['FLASKS3_URL_STYLE'] = 'path'
        ufs = "{{url_for('static', filename='bah.js')}}"
        exp = 'https://s3.amazonaws.com/foo/static/bah.js'
        self.assertEquals(self.client_get(ufs).data, six.b(exp))

    def test_url_for_url_style_invalid(self):
        """Tests that an exception is raised for invalid URL styles."""
        self.app.config['FLASKS3_URL_STYLE'] = 'balderdash'
        ufs = "{{url_for('static', filename='bah.js')}}"
        self.assertRaises(ValueError, self.client_get, six.b(ufs))


class S3Tests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.testing = True
        self.app.config['FLASKS3_BUCKET_NAME'] = 'foo'
        self.app.config['FLASKS3_USE_CACHE_CONTROL'] = True
        self.app.config['FLASKS3_CACHE_CONTROL'] = 'cache instruction'
        self.app.config['FLASKS3_CACHE_CONTROL'] = '3600'
        self.app.config['FLASKS3_HEADERS'] = {
            'Expires': 'Thu, 31 Dec 2037 23:59:59 GMT',
            'Content-Encoding': 'gzip',
        }
        self.app.config['FLASKS3_ONLY_MODIFIED'] = False

    def test__bp_static_url(self):
        """ Tests test__bp_static_url """
        bps = [Mock(static_url_path='/foo', url_prefix=None),
               Mock(static_url_path=None, url_prefix='/pref'),
               Mock(static_url_path='/b/bar', url_prefix='/pref'),
               Mock(static_url_path=None, url_prefix=None)]
        expected = [six.u('/foo'), six.u('/pref'), six.u('/pref/b/bar'), six.u('')]
        self.assertEquals(expected, [flask_s3._bp_static_url(x) for x in bps])

    def test__cache_config(self):
        """ Test that cache headers are set correctly. """
        new_app = Flask("test_cache_param")
        new_app.config['FLASKS3_USE_CACHE_CONTROL'] = True
        new_app.config['FLASKS3_CACHE_CONTROL'] = '3600'
        flask_s3.FlaskS3(new_app)
        expected = {'Cache-Control': '3600'}
        self.assertEqual(expected, new_app.config['FLASKS3_HEADERS'])

    @patch('os.walk')
    @patch('os.path.isdir')
    def test__gather_files(self, path_mock, os_mock):
        """ Tests the _gather_files function """
        self.app.static_folder = '/home'
        self.app.static_url_path = '/static'

        bp_a = Mock(static_folder='/home/bar', static_url_path='/a/bar',
                    url_prefix=None)
        bp_b = Mock(static_folder='/home/zoo', static_url_path='/b/bar',
                    url_prefix=None)
        bp_c = Mock(static_folder=None)

        self.app.blueprints = {'a': bp_a, 'b': bp_b, 'c': bp_c}
        dirs = {'/home': [('/home', None, ['.a'])],
                '/home/bar': [('/home/bar', None, ['b'])],
                '/home/zoo': [('/home/zoo', None, ['c']),
                              ('/home/zoo/foo', None, ['d', 'e'])]}
        os_mock.side_effect = dirs.get
        path_mock.return_value = True

        expected = {('/home/bar', six.u('/a/bar')): ['/home/bar/b'],
                    ('/home/zoo', six.u('/b/bar')): ['/home/zoo/c',
                                                     '/home/zoo/foo/d',
                                                     '/home/zoo/foo/e']}
        actual = flask_s3._gather_files(self.app, False)
        self.assertEqual(expected, actual)

        expected[('/home', six.u('/static'))] = ['/home/.a']
        actual = flask_s3._gather_files(self.app, True)
        self.assertEqual(expected, actual)

    @patch('os.walk')
    @patch('os.path.isdir')
    def test__gather_files_no_blueprints_no_files(self, path_mock, os_mock):
        """
        Tests that _gather_files works when there are no blueprints and
        no files available in the static folder
        """
        self.app.static_folder = '/foo'
        dirs = {'/foo': [('/foo', None, [])]}
        os_mock.side_effect = dirs.get
        path_mock.return_value = True

        actual = flask_s3._gather_files(self.app, False)
        self.assertEqual({}, actual)

    @patch('os.walk')
    @patch('os.path.isdir')
    def test__gather_files_bad_folder(self, path_mock, os_mock):
        """
        Tests that _gather_files when static folder is not valid folder
        """
        self.app.static_folder = '/bad'
        dirs = {'/bad': []}
        os_mock.side_effect = dirs.get
        path_mock.return_value = False

        actual = flask_s3._gather_files(self.app, False)
        self.assertEqual({}, actual)

    @patch('os.path.splitdrive', side_effect=ntpath.splitdrive)
    @patch('os.path.join', side_effect=ntpath.join)
    def test__path_to_relative_url_win(self, join_mock, split_mock):
        """ Tests _path_to_relative_url on Windows system """
        input_ = [r'C:\foo\bar\baz.css', r'C:\foo\bar.css',
                  r'\foo\bar.css']
        expected = ['/foo/bar/baz.css', '/foo/bar.css', '/foo/bar.css']
        for in_, exp in zip(input_, expected):
            actual = flask_s3._path_to_relative_url(in_)
            self.assertEquals(exp, actual)

    @unittest.skipIf(sys.version_info < (3, 0),
                     "not supported in this version")
    @patch('flask_s3.boto3')
    @patch("{}.open".format("builtins"), mock_open(read_data='test'))
    def test__write_files(self, key_mock):
        """ Tests _write_files """
        static_url_loc = '/foo/static'
        static_folder = '/home/z'
        assets = ['/home/z/bar.css', '/home/z/foo.css']
        exclude = ['/foo/static/foo.css', '/foo/static/foo/bar.css']
        # we expect foo.css to be excluded and not uploaded
        expected = [call(bucket=None, name=six.u('/foo/static/bar.css')),
                    call().set_metadata('Cache-Control', 'cache instruction'),
                    call().set_metadata('Expires', 'Thu, 31 Dec 2037 23:59:59 GMT'),
                    call().set_metadata('Content-Encoding', 'gzip'),
                    call().set_contents_from_filename('/home/z/bar.css')]
        flask_s3._write_files(key_mock, self.app, static_url_loc, static_folder, assets,
                              None, exclude)
        self.assertLessEqual(expected, key_mock.mock_calls)

    @patch('flask_s3.boto3')
    def test__write_only_modified(self, key_mock):
        """ Test that we only upload files that have changed """
        self.app.config['FLASKS3_ONLY_MODIFIED'] = True
        static_folder = tempfile.mkdtemp()
        static_url_loc = static_folder
        filenames = [os.path.join(static_folder, f) for f in ['foo.css', 'bar.css']]
        expected = []

        def IntIterator():
            i = 0
            while True:
                i += 1
                yield i

        data_iter = IntIterator()

        for filename in filenames:
            # Write random data into files
            with open(filename, 'wb') as f:
                if six.PY3:
                    data = str(data_iter)
                    f.write(data.encode())
                else:
                    data = str(data_iter.next())
                    f.write(data)

            # We expect each file to be uploaded
            expected.append(call.put_object(ACL='public-read',
                                            Bucket=None,
                                            Key=filename.lstrip("/"),
                                            Body=data,
                                            Metadata={},
                                            Expires='Thu, 31 Dec 2037 23:59:59 GMT',
                                            ContentEncoding='gzip'))

        files = {(static_url_loc, static_folder): filenames}

        hashes = flask_s3._upload_files(key_mock, self.app, files, None)

        # All files are uploaded and hashes are returned
        self.assertLessEqual(len(expected), len(key_mock.mock_calls))
        self.assertEquals(len(hashes), len(filenames))

        # We now modify the second file
        with open(filenames[1], 'wb') as f:
            data = str(next(data_iter))
            if six.PY2:
                f.write(data)
            else:
                f.write(data.encode())

        # We expect only this file to be uploaded
        expected.append(call.put_object(ACL='public-read',
                                        Bucket=None,
                                        Key=filenames[1].lstrip("/"),
                                        Body=data,
                                        Metadata={},
                                        Expires='Thu, 31 Dec 2037 23:59:59 GMT',
                                        ContentEncoding='gzip'))

        new_hashes = flask_s3._upload_files(key_mock, self.app, files, None,
                                            hashes=dict(hashes))
        #import pprint

        #pprint.pprint(zip(expected, key_mock.mock_calls))
        self.assertEquals(len(expected), len(key_mock.mock_calls))

    @patch('flask_s3.boto3')
    def test_write_binary_file(self, key_mock):
        """ Tests _write_files """
        self.app.config['FLASKS3_ONLY_MODIFIED'] = True
        static_folder = tempfile.mkdtemp()
        static_url_loc = static_folder
        filenames = [os.path.join(static_folder, 'favicon.ico')]

        for filename in filenames:
            # Write random data into files
            with open(filename, 'wb') as f:
                f.write(bytearray([120, 3, 255, 0, 100]))

        flask_s3._write_files(key_mock, self.app, static_url_loc, static_folder, filenames, None)

        expected = {
            'ACL': 'public-read',
            'Bucket': None,
            'Metadata': {},
            'ContentEncoding': 'gzip',
            'Body': b'x\x03\xff\x00d',
            'Key': filenames[0][1:],
            'Expires': 'Thu, 31 Dec 2037 23:59:59 GMT'}
        name, args, kwargs = key_mock.mock_calls[0]

        self.assertEquals(expected, kwargs)

    def test_static_folder_path(self):
        """ Tests _static_folder_path """
        inputs = [('/static', '/home/static', '/home/static/foo.css'),
                  ('/foo/static', '/home/foo/s', '/home/foo/s/a/b.css'),
                  ('/bar/', '/bar/', '/bar/s/a/b.css')]
        expected = [six.u('/static/foo.css'), six.u('/foo/static/a/b.css'),
                    six.u('/bar/s/a/b.css')]
        for i, e in zip(inputs, expected):
            self.assertEquals(e, flask_s3._static_folder_path(*i))

    @patch('flask_s3._write_files')
    def test__upload_uses_prefix(self, mock_write_files):
        s3_mock = Mock()
        local_path = '/local_path/static'
        file_paths = ['/local_path/static/file1', '/local_path/static/file2']
        files = {(local_path, '/static'): file_paths}

        flask_s3._upload_files(s3_mock, self.app, files, 's3_bucket')
        expected_call = call(
            s3_mock, self.app, '/static', local_path, file_paths, 's3_bucket', hashes=None)
        self.assertEquals(mock_write_files.call_args_list, [expected_call])

        for supported_prefix in ['foo', '/foo', 'foo/', '/foo/']:
            mock_write_files.reset_mock()
            self.app.config['FLASKS3_PREFIX'] = supported_prefix
            flask_s3._upload_files(s3_mock, self.app, files, 's3_bucket')
            expected_call = call(s3_mock, self.app, '/foo/static',
                                 local_path, file_paths, 's3_bucket', hashes=None)
            self.assertEquals(mock_write_files.call_args_list, [expected_call])

    @patch('flask_s3.current_app')
    def test__url_for_uses_prefix(self, mock_current_app):
        bucket_path = 'foo.s3.amazonaws.com'
        flask_s3.FlaskS3(self.app)
        mock_current_app.config = self.app.config
        mock_bind = mock_current_app.url_map.bind

        flask_s3.url_for('static', **{'filename': 'test_file.txt'})
        self.assertEqual(mock_bind.call_args_list, [call(bucket_path, url_scheme='https')])

        for supported_prefix in ['bar', '/bar', 'bar/', '/bar/']:
            mock_bind.reset_mock()
            self.app.config['FLASKS3_PREFIX'] = supported_prefix
            flask_s3.url_for('static', **{'filename': 'test_file.txt'})
            expected_path = '%s/%s' % (bucket_path, 'bar')
            self.assertEqual(mock_bind.call_args_list,
                             [call(expected_path, url_scheme='https')])


if __name__ == '__main__':
    unittest.main()
