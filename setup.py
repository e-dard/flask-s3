"""
Flask-S3
-------------

Easily serve your static files from Amazon S3.
"""

from setuptools import setup

requirements = open("requirements.txt", "r").read().splitlines()

setup(
    install_requires=requirements
)

