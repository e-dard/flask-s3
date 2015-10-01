"""
Flask-S3
-------------

Easily serve your static files from Amazon S3.
"""
from setuptools import setup


setup(
    name='Flask-S3',
    version='0.2.1',
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
