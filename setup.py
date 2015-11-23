"""
Flask-S3
-------------

Easily serve your static files from Amazon S3.
"""
from setuptools import setup

# Figure out the version; this could be done by importing the
# module, though that requires dependencies to be already installed,
# which may not be the case when processing a pip requirements
# file, for example.
def parse_version(asignee):
    import os, re
    here = os.path.dirname(os.path.abspath(__file__))
    version_re = re.compile(
        r'%s = (\(.*?\))' % asignee)
    with open(os.path.join(here, 'flask_s3.py')) as fp:
        for line in fp:
            match = version_re.search(line)
            if match:
                version = eval(match.group(1))
                return ".".join(map(str, version))
        else:
            raise Exception("cannot find version")
version = parse_version('__version__')
# above taken from miracle2k/flask-assets

setup(
    name='Flask-S3',
    version=version,
    url='http://github.com/e-dard/flask-s3',
    license='WTFPL',
    author='Edward Robinson',
    author_email='hi@edd.io',
    description='Seamlessly serve the static files of your Flask app from Amazon S3',
    long_description=__doc__,
    py_modules=['flask_s3'],
    zip_safe=False,
    include_package_data=True,
    platforms='any',
    install_requires=[
        'Flask',
        'Boto3>=1.1.1',
        'six'
    ],
    tests_require=['nose', 'mock'],
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: Other/Proprietary License',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ],
    test_suite = 'nose.collector'
)
