build: clean
	python3 setup.py sdist bdist_wheel

test_upload:
	python3 -m twine upload --verbose --repository testpypi dist/*

upload:
	python3 -m twine upload --repository pypi dist/*

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
