"""
Flask-S3
-------------

Easily serve your static files from Amazon S3.
"""
import re
import os

from setuptools import setup

def fpath(name):
    return os.path.join(os.path.dirname(__file__), name)


def read(fname):
    return open(fpath(fname)).read()


file_text = read(fpath('flask_s3.py'))
def grep(attrname):
    pattern = r"{0}\W*=\W*'([^']+)'".format(attrname)
    strval, = re.findall(pattern, file_text)
    return strval


def strip_comments(l):
    return l.split('#', 1)[0].strip()


setup(
    name='Flask-S3',
    version=grep('__version__'),
    license=grep('__license__'),
    author=grep('__author__'),
    url='http://github.com/e-dard/flask-s3',
    author_email='hi@edd.io',
    description='Seamlessly serve the static files of your Flask app from Amazon S3',
    long_description=__doc__,
    py_modules=['flask_s3'],
    keywords=['Flask', 'AWS', 'S3'],
    zip_safe=False,
    include_package_data=True,
    platforms='any',
    install_requires=[
        'Flask',
        'Boto>=2.5.2',
        'tqdm'
    ],
    tests_require=['nose2', 'mock'],
    test_suite='nose.collector',
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: Other/Proprietary License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ]
)
