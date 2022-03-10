# Deployment notes

Some notes on deploying this software component into kubernetes.

First, you need to know where you are working, usual options are:

* tools -- the actual Toolforge kubernetes cluster
* toolsbeta -- the Toolforge development / stagging environment
* devel-kind -- a kubernetes kind deployment in your laptop

Then replace your option with `$WHERE` in the following operations.

Deploy from stratch:
```
kubectl apply -k deployment/$WHERE
```

View diff for pending updates:
```
kubectl diff -k deployment/$WHERE
```

View generated config:
```
kubectl kustomize deployment/$WHERE
```

View current status of the deployment inside kubernetes:
```
kubectl get -k deployment/$WHERE
```

Delete everything inside kubernetes (live service shutdown):
```
kubectl delete -k deployment/$WHERE
```

See also:
  https://kubernetes.io/docs/tasks/manage-kubernetes-objects/kustomization/
