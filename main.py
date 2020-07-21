"""A Flask application wrapper around the App Engine Search API."""

import logging
import os
import re
import string

from google.appengine.api import search
from google.appengine.runtime import apiproxy_errors

import flask
import werkzeug.exceptions

# This is also used as the name of the search index
_USERNAME = os.environ.get('BASIC_AUTH_USERNAME')
"""String expected HTTP basic authentication username."""

_PASSWORD = os.environ.get('BASIC_AUTH_PASSWORD')
"""String expected HTTP basic authentication password."""

### Search API wrapper

_BATCH_SIZE = search.MAXIMUM_DOCUMENTS_PER_PUT_REQUEST
"""Integer maximum number of documents the index can handle per request."""

# Search API imposes this limit to ensure the reliability of the service
_SAFETY_LIMIT = 15000
"""Integer maximum number of documents that can be put/deleted per minute."""

_VISIBLE_PRINTABLE_ASCII = frozenset(
    set(string.printable) - set(string.whitespace))
"""frozenset of valid ASCII characters for the document identifier."""

# Field names are case sensitive and can only contain ASCII characters.
# They must start with a letter and can contain letters, digits, or
# underscores. A field name cannot be longer than 500 characters.
_FIELD_NAME = 't'
"""String default field name for the text in a document."""

def _is_valid_doc_id(doc_id):
    """Return True if doc_id is a valid ASCII document identifier.

    A doc_id must contain only visible, printable ASCII characters (ASCII
    codes 33 through 126 inclusive) and be no longer than 500 characters.
    A document identifier cannot begin with an exclamation point ('!'), and
    it can't begin and end with double underscores ("__").

    Args:
        doc_id: String ASCII document identifier to test.
    Returns:
        True if doc_id is a valid ASCII document identifier. False otherwise.
    """
    if isinstance(doc_id, str):
        length = len(doc_id)
        if (length <= 0) or (search.MAXIMUM_DOCUMENT_ID_LENGTH < length):
            return False
        if doc_id.startswith('!'):
            return False
        if doc_id.startswith('__') and doc_id.endswith('__'):
            return False
        for c in doc_id:
            if c not in _VISIBLE_PRINTABLE_ASCII:
                return False
        return True
    return False

def _strip_operators(query, replacement=' '):
    """Return query without the relational operators (:=<>).

    Args:
        query: String search query.
        replacement: Optional string replacement string for the relational
            operators. Defaults to space.
    Returns:
        String query without the relational operators (:=<>).
    """
    if not isinstance(query, basestring):
        raise TypeError('query must be a string.')
    if not isinstance(replacement, basestring):
        raise TypeError('replacement must be a string.')
    return re.sub('[:=<>]', replacement, query)

def _delete(search_index, ids):
    """Delete documents with document identifiers in ids.

    Args:
        search_index: search.Index object to the index from which to delete.
        ids: List of string document identifiers to delete.
    Raises:
        ValueError if ids is longer than the Search API safety limit.
    """
    length = len(ids)
    if length > _SAFETY_LIMIT:
        raise ValueError('ids exceeds the Search API safety limit.')

    futures = []
    for i in xrange(0, length, _BATCH_SIZE):
        futures.append(search_index.delete_async(ids[i:i+_BATCH_SIZE]))

    # Wait for the futures to complete
    for future in futures:
        try:
            future.get_result()
        except search.DeleteError:
            logging.error('Unable to delete documents from search index.')
            continue
        except apiproxy_errors.DeadlineExceededError:
            logging.error('Deadline exceeded for Search API delete call.')
        except apiproxy_errors.OverQuotaError:
            logging.error(
                'Quota exceeded for Search API {0} delete calls.'.format(
                    length))
            return

def _put(search_index, documents):
    """Put documents in the search index.

    If a document with the same document identifier already exists in the
    search index, then that document is replaced.

    Args:
        search_index: search.Index object to the index to which to put.
        documents: List of search.Document objects to put.
    Raises:
        ValueError if documents is longer than the Search API safety limit.
    """
    documents = [document for document in documents
                 if isinstance(document, search.Document)]
    length = len(documents)
    if length > _SAFETY_LIMIT:
        raise ValueError('documents exceeds the Search API safety limit.')

    futures = []
    for i in xrange(0, length, _BATCH_SIZE):
        futures.append(search_index.put_async(documents[i:i+_BATCH_SIZE]))

    # Wait for the futures to complete
    for future in futures:
        try:
            future.get_result()
        except search.PutError:
            logging.error('Unable to put documents in search index.')
            continue
        except apiproxy_errors.DeadlineExceededError:
            logging.error('Deadline exceeded for Search API put call.')
        except apiproxy_errors.OverQuotaError:
            logging.error(
                'Quota exceeded for Search API {0} put calls.'.format(
                    length))
            return

def _search(search_index, query):
    """Return document IDs matching a global search of the index for query.

    Args:
        search_index: search.Index object to the index to search.
        query: String search query.
    Returns:
        List of string document identifiers whose full text match a global
        search of the index for query.
    """
    if not isinstance(query, basestring):
        raise TypeError('query must be a non-empty string.')
    query = query.strip()
    length = len(query)
    if (length <= 0) or (search.MAXIMUM_QUERY_LENGTH < length):
        return []

    query = _strip_operators(query)
    options_arguments = {
        'limit': search.MAXIMUM_DOCUMENTS_RETURNED_PER_SEARCH,
        'ids_only': True
    }
    options = search.QueryOptions(**options_arguments)
    try:
        # Create search.Query in try-catch to catch QueryError
        # if the search query is not parseable
        query_object = search.Query(query, options=options)
        result = search_index.search(query_object)
    except search.Error:
        return []
    except apiproxy_errors.DeadlineExceededError:
        logging.error('Deadline exceeded for Search API search call.')
        return []
    except apiproxy_errors.OverQuotaError:
        logging.error('Quota exceeded for Search API search call.')
        return []
    else:
        return [doc.doc_id for doc in result.results]

### WSGI application

def get_search_index():
    """Return the search index if authenticated or None."""
    if isinstance(_USERNAME, basestring) and isinstance(_PASSWORD, basestring):
        # HTTP basic authentication
        if flask.request.authorization is None:
            return None
        if ((flask.request.authorization.username == _USERNAME) and
            (flask.request.authorization.password == _PASSWORD)):
            return search.Index(name=_USERNAME)
    return None

def delete_view():
    """Delete the indicated documents from the search index."""
    search_index = get_search_index()
    if search_index is None:
        return flask.abort(401)
    request_json = flask.request.get_json(silent=True)
    if isinstance(request_json, list):
        ids = []
        for entry in request_json:
            try:
                doc_id = entry.encode('ascii')
            except UnicodeEncodeError:
                continue
            else:
                if _is_valid_doc_id(doc_id):
                    ids.append(doc_id)
        try:
            _delete(search_index, ids)
        except ValueError:
            return flask.abort(413)
    return ''

def get_view():
    """Run the specified search query and return the result."""
    search_index = get_search_index()
    if search_index is None:
        return flask.abort(401)

    query = flask.request.values.get('q')
    result = []
    if isinstance(query, basestring) and (len(query) > 0):
        result = _search(search_index, query)

    response = flask.jsonify(result)
    response.content_type = 'application/json; charset=utf-8'
    return response

def put_view():
    """Convert JSON payload to documents and put them in the search index."""
    search_index = get_search_index()
    if search_index is None:
        return flask.abort(401)
    request_json = flask.request.get_json(silent=True)
    if isinstance(request_json, dict):
        documents = []
        for k, v in request_json.iteritems():
            try:
                doc_id = k.encode('ascii')
            except UnicodeEncodeError:
                continue
            if (_is_valid_doc_id(doc_id) and
                isinstance(v, basestring) and (len(v) > 0)):
                documents.append(search.Document(
                    doc_id=doc_id, fields=[search.TextField(
                        name=_FIELD_NAME,
                        value=v[:search.MAXIMUM_FIELD_VALUE_LENGTH])]))
        try:
            _put(search_index, documents)
        except ValueError:
            return flask.abort(413)
    return ''

app = flask.Flask(__name__)
"""Flask application."""

app.add_url_rule('/', 'DELETE', delete_view, methods=['DELETE'])
app.add_url_rule('/', 'GET', get_view, methods=['GET'])
app.add_url_rule('/', 'PUT', put_view, methods=['POST', 'PUT'])

def json_error_handler(error):
    """Return the error as a JSON response."""
    response = flask.jsonify(error={
        'code': error.code,
        'message': 'Oops! This is embarrassing. An error occurred.'})
    response.content_type = 'application/json; charset=utf-8'
    response.status_code = error.code
    return response

# Register json_error_handler for all possible exceptions
for code in werkzeug.exceptions.default_exceptions.iterkeys():
    app.register_error_handler(code, json_error_handler)
