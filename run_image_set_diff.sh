#!/bin/bash

source common.sh

./dpxdt/tools/image_set_diff.py\
    --release_server_prefix=${RELEASE_SERVER_PREFIX} \
    "$@"
