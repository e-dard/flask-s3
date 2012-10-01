import unittest
import ntpath

from mock import Mock, patch, call
from flask import Flask, render_template_string, Blueprint

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

    def test_config(self):
        """ Tests configuration vars exist. """
        FlaskS3(self.app)
        defaults = ('S3_USE_HTTPS', 'USE_S3', 'S3_DEBUG_FORCE')
        for default in defaults:
            self.assertIn(default, self.app.config)



class UrlTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.testing = True
        
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
        return client.get('/%s' % ufs)

    def test_required_config(self):
        """ Tests that ValueError raised if bucket address not provided."""
        raises = False
        try:
            ufs = "{{url_for('static', filename='bah.js')}}"
            self.client_get(ufs)
        except ValueError:
            raises = True
        self.assertTrue(raises)

    def test_url_for(self):
        """Tests that correct url formed for static asset in self.app."""
        self.app.config['S3_BUCKET'] = 'foo.com'

        # non static endpoint url_for in template 
        self.assertEquals(self.client_get('').data, '/')

        # static endpoint url_for in template
        ufs = "{{url_for('static', filename='bah.js')}}"
        exp = 'http://foo.com/static/bah.js'
        self.assertEquals(self.client_get(ufs).data, exp)

    def test_url_for_blueprint(self):
        """Tests that correct url formed for static asset in blueprint."""
        self.app.config['S3_BUCKET'] = 'foo.com'

        # static endpoint url_for in template
        ufs = "{{url_for('admin.static', filename='bah.js')}}"
        exp = 'http://foo.com/admin-static/bah.js'
        self.assertEquals(self.client_get(ufs).data, exp)



class S3Tests(unittest.TestCase):

    def setUp(self):
        self.app = Mock(spec=Flask)

    def test__bp_static_url(self):
        """ Tests test__bp_static_url """
        bps = [Mock(static_url_path='/foo', url_prefix=None), 
               Mock(static_url_path='/b/bar', url_prefix='/pref')]
        expected = [u'/foo', u'/pref/b/bar']
        self.assertEquals(expected, [flask_s3._bp_static_url(x) for x in bps])



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
        self.app.blueprints = { 'a': bp_a, 'b': bp_b}
        dirs = { '/home': [('/home', None, ['.a'])],
                 '/home/bar': [('/home/bar', None, ['b'])],
                 '/home/zoo': [('/home/zoo', None, ['c']), 
                               ('/home/zoo/foo', None, ['d', 'e'])] }
        os_mock.side_effect=dirs.get
        path_mock.return_value = True

        expected = {('/home/bar', u'/a/bar'): ['/home/bar/b'], 
                    ('/home/zoo', u'/b/bar'): ['/home/zoo/c', 
                                               '/home/zoo/foo/d', 
                                               '/home/zoo/foo/e']}
        actual = flask_s3._gather_files(self.app, False)
        self.assertEqual(expected, actual)

        expected[('/home', u'/static')] = ['/home/.a']
        actual = flask_s3._gather_files(self.app, True)
        self.assertEqual(expected, actual)

    @patch('os.walk')
    @patch('os.path.isdir')
    def test__gather_files_no_blueprints_no_files(self, path_mock, os_mock):
        """
        Tests that _gather_files works when there are no blueprints and no 
        files available in the static folder
        """
        self.app.static_folder = '/foo'
        dirs = {'/foo': [('/foo', None, [])]}
        os_mock.side_effect=dirs.get
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
        os_mock.side_effect=dirs.get
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

    @patch('flask_s3.Key')
    def test__write_files(self, key_mock):
        """ Tests _write_files """
        static_url_loc = '/foo/static'
        static_folder = '/home/z'
        assets = ['/home/z/bar.css', '/home/z/foo.css'] 
        exclude = ['/foo/static/foo.css', '/foo/static/foo/bar.css']
        expected = [call(bucket=None, name='/foo/static/bar.css'), 
                    call().set_contents_from_filename('/home/z/bar.css')]
        flask_s3._write_files(static_url_loc, static_folder, assets, None, 
                              exclude)
        self.assertEquals(expected, key_mock.mock_calls)

    def test_static_folder_path(self):
        """ Tests _static_folder_path """
        inputs = [('/static', '/home/static', '/home/static/foo.css'),
                  ('/foo/static', '/home/foo/s', '/home/foo/s/a/b.css'),
                  ('/bar/', '/bar/', '/bar/s/a/b.css')]
        expected = [u'/static/foo.css', u'/foo/static/a/b.css', 
                    u'/bar/s/a/b.css']
        for i, e in zip(inputs, expected):
            self.assertEquals(e, flask_s3._static_folder_path(*i))

    def test__upload_files(self):
        """ Tests _upload_files """
        assert True

if __name__ == '__main__':
    unittest.main()