"""Offline boundaries shared by every test, including the original API tests."""

import os
import socket

# Set these before test modules import the application and its SDKs.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
os.environ["LANGSMITH_TRACING"] = "false"

import boto3
import pytest
from sentence_transformers import CrossEncoder, SentenceTransformer


@pytest.fixture(autouse=True)
def offline_boundaries(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must use fakes for network, AWS and model loading.")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(boto3, "client", blocked)
    monkeypatch.setattr(boto3.session.Session, "client", blocked)
    monkeypatch.setattr(SentenceTransformer, "__init__", blocked)
    monkeypatch.setattr(CrossEncoder, "__init__", blocked)
