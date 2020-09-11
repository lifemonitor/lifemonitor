import json
import logging
import os
import tempfile
import zipfile

import flask
import requests

RO_CRATE_METADATA_FILENAME = "ro-crate-metadata.jsonld"
RO_CRATE_TEST_DEFINITION_FILENAME = "test-metadata.json"

logger = logging.getLogger()


def bool_from_string(s) -> bool:
    if s is None or s == "":
        return None
    if s.lower() in {'t', 'true', '1'}:
        return True
    if s.lower() in {'f', 'false', '0'}:
        return False
    raise ValueError(f"Invalid string value for boolean. Got '{s}'")


def to_camel_case(snake_str) -> str:
    """
    Convert snake_case string to a camel_case string
    :param snake_str:
    :return:
    """
    return ''.join(x.title() for x in snake_str.split('_'))


def download_url(url, target_path=None, token=None):
    with requests.Session() as session:
        if token:
            session.headers['Authorization'] = f'Bearer {token}'
        with session.get(url, stream=True) as r:
            r.raise_for_status()
            if not target_path:
                target_path = tempfile.mktemp()
            with open(target_path, 'wb') as fd:
                for chunk in r.iter_content(chunk_size=8192):
                    fd.write(chunk)
    return target_path


def extract_zip(archive_path, target_path=None):
    if not target_path:
        target_path = tempfile.mkdtemp()
    with zipfile.ZipFile(archive_path, "r") as zip_ref:
        zip_ref.extractall(target_path)
    return target_path


def load_ro_crate_metadata(roc_path):
    file_path = os.path.join(roc_path, RO_CRATE_METADATA_FILENAME)
    with open(file_path) as data_file:
        logger.info("Loading RO Crate Metadata @ %s", file_path)
        data = json.load(data_file)
        logger.debug("RO Crate Metadata: %r", data)
        return data


def load_test_definition_filename(filename):
    with open(filename) as f:
        return json.load(f)


def get_test_definition_path(roc_path):
    return os.path.join(roc_path, "test", RO_CRATE_TEST_DEFINITION_FILENAME)


def search_for_test_definition(roc_path, ro_crate_metadata: dict):
    # first search on the root roc_path for a test_definition file
    filename = get_test_definition_path(roc_path)
    if os.path.exists(filename):
        return load_test_definition_filename(filename)
    return None


def push_request_to_session(name):
    flask.session[f'{name}_next_endpoint'] = flask.request.endpoint
    flask.session[f'{name}_next_args'] = flask.request.args
    flask.session[f'{name}_next_forms'] = flask.request.form


def pop_request_from_session(name):
    endpoint = flask.session.pop(f'{name}_next_endpoint', None)
    if endpoint:
        return {
            "endpoint": endpoint,
            "args": flask.session.pop(f'{name}_next_args'),
            "form": flask.session.pop(f'{name}_next_forms')
        }
    return None
