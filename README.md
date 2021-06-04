flask-s3-ng
===========

Seamlessly serve the static assets of your Flask app from Amazon S3.

Project description
-------------------

This project is base on Flask-S3 project. This great project has unmaintained for a lot time and this fork aims to get updated.

In this fork, Python 2 support was removed. 

Installation
------------

Install Flask-S3 via pypi:

    pip install flask-s3-ng

New features
------------

This fork offer some new features:

- Progress bar while it is updating statics
- Support for other S3 providers but AWS.

Support for other S3 providers
++++++++++++++++++++++++++++++

If you use a different provider than AWS S3, you can use the configuration parameter `FLASKS3_ENDPOINT_URL`.

For example, if you're using Scaleway provider for S3 storage, your `FLASKS3_ENDPOINT_URL` is: `https://s3.nl-ams.scw.cloud`.

Documentation
-------------

Most of the original documentation is currently valid.

For additional informacion or example you can refer to the original repo.

The latest documentation for Flask-S3 can be found [here](https://flask-s3.readthedocs.io/en/latest/).


