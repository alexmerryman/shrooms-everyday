#!/bin/bash
set -eo pipefail
rm -rf pkg
pip3 install --target pkg/python -r requirements.txt
cd pkg
zip -r shrooms-everyday-layer.zip .