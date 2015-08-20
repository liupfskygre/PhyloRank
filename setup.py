from distutils.core import setup

import os

def version():
    setupDir = os.path.dirname(os.path.realpath(__file__))
    versionFile = open(os.path.join(setupDir, 'phylorank', 'VERSION'))
    return versionFile.read().strip()

setup(
    name='phylorank',
    version=version(),
    author='Donovan Parks',
    author_email='donovan.parks@gmail.com',
    packages=['phylorank'],
    scripts=['bin/phylorank'],
    package_data={'phylorank' : ['VERSION']},
    url='http://pypi.python.org/pypi/phylorank/',
    license='GPL3',
    description='Assigns taxonomic ranks based on evolutionary divergence.',
    long_description=open('README.md').read(),
    install_requires=[
        "scikit-bio >= 0.4.0",
        "biolib >= 0.0.10"],
)