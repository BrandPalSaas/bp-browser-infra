#!/bin/bash

# Port forward the controller service to localhost:8000
kubectl port-forward service/controller 8000:8000