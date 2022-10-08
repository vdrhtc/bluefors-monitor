import setuptools

setuptools.setup(
    name="bluefors_slave",
    py_modules=["bluefors_slave"],
    install_requires=["overseer_slave","loggingserver"],
    version="1.0b4",
    author="Gleb Fedorov",
    author_email="vdrhtc@gmail.com",
    description="Bluefors interface for the Overseer",
    long_description='''This package is to monitor the state of Bluefors fridges''',
    long_description_content_type="text/markdown",
    url="https://github.com/vdrhtc/bluefors-monitor",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
    ],
)
