#!/bin/bash

# see https://phabricator.wikimedia.org/T303931

where=$(cat /etc/wmcs-project 2>/dev/null || echo "devel-kind")
kubectl apply -k deployment/${where}
