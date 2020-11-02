import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name='gpu-watchmen',  
    version='0.2.2',
    author="Tong Zhu",
    author_email="tzhu1997@outlook.com",
    description="watchmen for GPU scheduling",
    long_description_content_type="text/markdown",
    long_description=long_description,
    url="https://github.com/Spico197/watchmen",
    packages=[
        "watchmen"
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux"
    ],
    python_requires='>=3.6',
    install_requires=[
        "apscheduler>=3.6.3",
        "flask>=1.1.2",
        "gpustat>=0.6.0",
        "pydantic>=1.7.1",
        "requests>=2.24.0",
    ],
    package_data={
        'watchmen' : [
            'templates/*.html'
        ],
    },
    include_package_data=True,
)
