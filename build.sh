#!/usr/bin/env bash

pip install --upgrade pip

pip install setuptools==69.5.1

pip install -r requirements.txt

python manage.py collectstatic --noinput

python manage.py migrate