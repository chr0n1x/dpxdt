#!/bin/bash

source common.sh

./dpxdt/runserver.py \
    --local_queue_workers \
    --phantomjs_binary=$PHANTOMJS_BINARY \
    --phantomjs_script=$CAPTURE_SCRIPT \
    --phantomjs_timeout=20 \
    --release_server_prefix=${RELEASE_SERVER_PREFIX} \
    --queue_server_prefix=${QUEUE_SERVER_PREFIX} \
    --queue_poll_seconds=10 \
    --pdiff_timeout=20 \
    --reload_code \
    --port=5000 \
    --verbose \
    --ignore_auth \
    $@
