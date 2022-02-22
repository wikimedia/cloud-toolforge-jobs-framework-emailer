# Development enviroment

To set up a development environment for this software piece you need the following:

* a kubernetes cluster (in your laptop, probably based on minikube, kind or similar)
* a working jobs-framework-api deployment (refer to devel notes on its own source tree)
* a working jobs-framework-cli environment (refet to devel notes on its own source tree)

There should be a Toolforge-like enviroment working, so you can run jobs and the pod API
can see some action.

It is highly recommended to have plain docker installed on your development machine.
The CI script depends on it.

# QA, tests and CI

Running tox should trigger flake8, black and automated tests.

To mirror on your laptop what the gerrit CI would do, you have the convenience script:

```
./run-local-ci.sh
```

Which runs tox inside a docker container.

# Initial k8s deployment

Once you are ready to deploy the emailer for the first time, follow instructions in
the `deployment/` directory.

If you are developing on the kind (https://kind.sigs.k8s.io/) tool, then you need to deploy
the emailer like this:

```
kubectl apply -k deployment/devel-kind
```

# Development iteration

Once initially deployed, you can quickly iterate on patches/changes using this command line:

```
./run-local-ci.sh && docker build --tag jobs-emailer . && kind load docker-image jobs-emailer:latest && kubectl -n jobs-emailer rollout restart deployment/jobs-emailer
```
