__version__ = '0.8.4'

import os

from setuptools import setup, find_packages

try:
    here = os.path.abspath(os.path.dirname(__file__))
    README = open(os.path.join(here, 'README.rst')).read()
    CHANGES = open(os.path.join(here, 'CHANGES.txt')).read()
except IOError:
    README = CHANGES = ''

INSTALL_REQUIRES = [
    'setuptools',
    'zope.component',
    'ZODB',
    'zope.index >= 3.5.0',
    'six'
]

TESTING_EXTRAS = ['nose', 'coverage']
DOCS_EXTRAS = ['Sphinx']

setup(name='zerodbext.catalog',
      version=__version__,
      description='Searching and indexing based on zope.index. Fork of repoze.catalog',
      long_description=README + '\n\n' + CHANGES,
      classifiers=[
        "Intended Audience :: Developers",
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: Implementation :: CPython",
        "Topic :: Internet :: WWW/HTTP :: Indexing/Search",
        ],
      keywords='indexing catalog search',
      author="ZeroDB",
      license="BSD-derived (http://www.repoze.org/LICENSE.txt)",
      packages=find_packages(),
      include_package_data=True,
      namespace_packages=['zerodbext'],
      zip_safe=False,
      tests_require = INSTALL_REQUIRES,
      install_requires = INSTALL_REQUIRES,
      extras_require = {
            'benchmark': ['PyChart'],
            'testing': TESTING_EXTRAS,
            'docs': DOCS_EXTRAS,
        },
      test_suite="zerodbext.catalog",
)
