"""Test the Flask application."""

import unittest

from google.appengine.api import search
from google.appengine.ext import testbed

import webtest

import main

main._USERNAME = 'username'
main._PASSWORD = 'password'

DATA = {
    'Doraemon': 'Robotic cat from the future.',
    'Garfield': 'Loves lasagna. Hates Mondays.',
    'Heathcliff': 'What a happy cat. Full content goes here.',
    'Hello_Kitty': 'Sells herself out to any product.',
    'Top_Cat': 'Fancy. Lives in an alley.'
}
"""Dictionary of test data to use."""

class BaseTestCase(unittest.TestCase):

    """Base TestCase for tests that require the App Engine testbed.

    This class takes care of activating and deactivating the testbed and
    associated stubs.
    """

    def setUp(self):
        """Activate the testbed."""
        self.testbed = testbed.Testbed()
        self.testbed.activate()
        self.testbed.init_search_stub()

        self.search_index = None

    def tearDown(self):
        """Deactivate the testbed."""
        self.testbed.deactivate()

    def assertSearchIndexSize(self, size):
        """Test self.search_index has size documents."""
        if isinstance(self.search_index, search.Index):
            self.assertEqual(len(self.search_index.get_range(ids_only=True)),
                             size)

class SearchTest(BaseTestCase):
    def setUp(self):
        super(SearchTest, self).setUp()

        self.search_index = search.Index(name='TestIndex')
        """search.Index object to the search index to use in the tests."""

        self.assertSearchIndexSize(0)

    def test_constants(self):
        """Test the module constants."""
        self.assertLess(main._BATCH_SIZE, main._SAFETY_LIMIT)
        self.assertEqual(len(main._FIELD_NAME), 1)
        self.assertIn(main._FIELD_NAME, main._VISIBLE_PRINTABLE_ASCII)

    def test_is_valid_doc_id(self):
        """Test whether a document identifier is valid."""
        for value in [None, 42, '', [], 'i' * 501, u'fo\u00f6b\u00e4r',
                      'foo bar', 'foo bar baz', '!foobar', '__foobar__']:
            self.assertFalse(main._is_valid_doc_id(value))
        for value in ['foo', 'bar', 'foobar', 'foo!bar', 'foobar!',
                      '__foobar', 'foobar__', ''.join(
                          main._VISIBLE_PRINTABLE_ASCII)] + DATA.keys():
            self.assertTrue(main._is_valid_doc_id(value))
            self.assertFalse(main._is_valid_doc_id('!' + value))
            self.assertFalse(main._is_valid_doc_id('__' + value + '__'))

    def test_strip_operators(self):
        """Test removing relational operators from a search query."""
        for value in [None, 42, []]:
            self.assertRaises(TypeError, main._strip_operators, value)
            self.assertRaises(TypeError, main._strip_operators,
                              'foobar', value)
        for value, expected in [
            ('', ''),
            ('foo', 'foo'),
            ('foobar', 'foobar'),
            ('foo = bar', 'foo   bar'),
            ('foo: bar', 'foo  bar'),
            ('foo < bar', 'foo   bar'),
            ('foo > bar', 'foo   bar'),
            ('foo := bar', 'foo    bar'),
            (u'fo\u00f6b\u00e4r', u'fo\u00f6b\u00e4r'),
            (u'fo\u00f6 = b\u00e4r', u'fo\u00f6   b\u00e4r'),
            (u'fo\u00f6: b\u00e4r', u'fo\u00f6  b\u00e4r'),
            (u'fo\u00f6 < b\u00e4r', u'fo\u00f6   b\u00e4r'),
            (u'fo\u00f6 > b\u00e4r', u'fo\u00f6   b\u00e4r'),
            (u'fo\u00f6 := b\u00e4r', u'fo\u00f6    b\u00e4r')]:
            self.assertEqual(main._strip_operators(value), expected)
            # Test replacing with space explicitly
            self.assertEqual(main._strip_operators(value, ' '), expected)

        # Test replacing with the empty string
        for value, expected in [
            ('foo = bar', 'foo  bar'),
            ('foo: bar', 'foo bar'),
            ('foo < bar', 'foo  bar'),
            ('foo > bar', 'foo  bar'),
            ('foo := bar', 'foo  bar')]:
            self.assertEqual(main._strip_operators(value, ''), expected)

        # Test replacing with underscore
        for value, expected in [
            ('foo = bar', 'foo _ bar'),
            ('foo: bar', 'foo_ bar'),
            ('foo < bar', 'foo _ bar'),
            ('foo > bar', 'foo _ bar'),
            ('foo := bar', 'foo __ bar')]:
            self.assertEqual(main._strip_operators(value, '_'), expected)

    def test_delete(self):
        """Test deleting documents from the search index."""
        self.assertRaises(ValueError, main._delete,
                          self.search_index, ['i'] * (main._SAFETY_LIMIT + 1))
        self.assertSearchIndexSize(0)
        main._delete(self.search_index, ['i'] * main._SAFETY_LIMIT)
        self.assertSearchIndexSize(0)

    def test_put(self):
        """Test putting documents in the search index."""
        self.assertRaises(
            ValueError, main._put, self.search_index, [
                search.Document(doc_id=str(i), fields=[
                    search.TextField(name=main._FIELD_NAME, value=str(i))])
                for i in xrange(0, main._SAFETY_LIMIT + 1)])
        self.assertSearchIndexSize(0)
        main._put(self.search_index, [
            search.Document(doc_id=k, fields=[
                search.TextField(name=main._FIELD_NAME, value=v)])
            for k, v in DATA.items()])
        self.assertSearchIndexSize(len(DATA))

        for value in [['foobar'], ['Meowth']]:
            main._delete(self.search_index, value)
            self.assertSearchIndexSize(len(DATA))

        main._delete(self.search_index, ['Doraemon'])
        self.assertSearchIndexSize(len(DATA) - 1)
        main._delete(self.search_index, ['Garfield'])
        self.assertSearchIndexSize(len(DATA) - 2)
        main._delete(self.search_index, DATA.keys())
        self.assertSearchIndexSize(0)

    def test_search(self):
        """Test searching documents in the search index."""
        for value in [None, 42, []]:
            self.assertRaises(TypeError, main._search,
                              self.search_index, value)
        for value in ['', 'q' * (search.MAXIMUM_QUERY_LENGTH + 1),
                      'foobar', 'Robotic', 'robotic', 'Future', 'future',
                      'cat']:
            self.assertEqual(main._search(self.search_index, value), [])
            self.assertSearchIndexSize(0)

        main._put(self.search_index, [
            search.Document(doc_id=k, fields=[
                search.TextField(name=main._FIELD_NAME, value=v)])
            for k, v in DATA.items()])
        self.assertSearchIndexSize(len(DATA))
        for value, expected in [
            ('Robotic', ['Doraemon']),
            ('robotic', ['Doraemon']),
            ('Future', ['Doraemon']),
            ('future', ['Doraemon']),
            ('CAT', ['Doraemon', 'Heathcliff']),
            ('Cat', ['Doraemon', 'Heathcliff']),
            ('cat', ['Doraemon', 'Heathcliff']),
            ('Loves lasagna', ['Garfield']),
            ('Hates Mondays.', ['Garfield']),
            ('Fancy', ['Top_Cat']),
            ('fancy', ['Top_Cat'])]:
            self.assertEqual(main._search(self.search_index, value), expected)
            self.assertSearchIndexSize(len(DATA))
        main._delete(self.search_index, ['Doraemon'])
        self.assertSearchIndexSize(len(DATA) - 1)
        for value, expected in [
            ('Robotic', []),
            ('robotic', []),
            ('Future', []),
            ('future', []),
            ('CAT', ['Heathcliff']),
            ('Cat', ['Heathcliff']),
            ('cat', ['Heathcliff']),
            ('Loves lasagna', ['Garfield']),
            ('Hates Mondays.', ['Garfield']),
            ('Fancy', ['Top_Cat']),
            ('fancy', ['Top_Cat'])]:
            self.assertEqual(main._search(self.search_index, value), expected)
            self.assertSearchIndexSize(len(DATA) - 1)

class WSGITest(BaseTestCase):
    def setUp(self):
        super(WSGITest, self).setUp()

        # Enable Flask debugging
        main.app.debug = True

        # Wrap the WSGI application in a TestApp
        self.app = webtest.TestApp(main.app)
        self.app.authorization = ('Basic', (main._USERNAME, main._PASSWORD))

        self.url = '/'
        """String URL the search index is mapped under."""

        self.search_index = search.Index(name=main._USERNAME)
        """search.Index object to the search index to use in the tests."""

        self.assertSearchIndexSize(0)

    def test_bad_authentication(self):
        """Test bad HTTP basic authentication."""
        for value in [None, ('Basic', ('foo', 'bar')),
                      ('Basic', ('foo', main._PASSWORD)),
                      ('Basic', (main._USERNAME, 'bar'))]:
            self.app.authorization = value
            response = self.app.delete(self.url, status=401)
            self.assertEqual(response.status_int, 401)
            response = self.app.get(self.url, status=401)
            self.assertEqual(response.status_int, 401)
            response = self.app.post(self.url, status=401)
            self.assertEqual(response.status_int, 401)
            response = self.app.put(self.url, status=401)
            self.assertEqual(response.status_int, 401)

    def test_empty(self):
        """Test empty input."""
        response = self.app.delete(self.url, '')
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)
        response = self.app.delete_json(self.url, [])
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)
        response = self.app.delete_json(self.url, {})
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)

        response = self.app.post(self.url, '')
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)
        response = self.app.post_json(self.url, [])
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)
        response = self.app.post_json(self.url, {})
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)

        response = self.app.put(self.url, '')
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)
        response = self.app.put_json(self.url, [])
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)
        response = self.app.put_json(self.url, {})
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)

    def test_add(self):
        """Test adding to the search index."""
        response = self.app.post_json(self.url, dict([
            ('!' + k, v) for k, v in DATA.items()]))
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)
        response = self.app.post_json(self.url, dict([
            (u'{0}_c\u00e4t'.format(k), v) for k, v in DATA.items()]))
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)
        response = self.app.put_json(self.url, dict([
            ('__' + k + '__', v) for k, v in DATA.items()]))
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)

        response = self.app.post_json(self.url, DATA)
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(len(DATA))
        for value in [['foobar'], ['Meowth'],
                      ['!' + k for k in DATA],
                      [u'{0}_c\u00e4t'.format(k) for k in DATA],
                      ['__' + k + '__' for k in DATA]]:
            response = self.app.delete_json(self.url, value)
            self.assertEqual(response.status_int, 200)
            self.assertSearchIndexSize(len(DATA))

        response = self.app.delete_json(self.url, DATA.keys()[:2])
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(len(DATA) - 2)
        response = self.app.put_json(self.url, DATA)
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(len(DATA))
        response = self.app.delete_json(self.url, DATA.keys())
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(0)

    def test_safety_limit(self):
        """Test exceeding the safety limit."""
        response = self.app.delete_json(self.url, [
            str(i) for i in xrange(0, main._SAFETY_LIMIT + 1)], status=413)
        self.assertEqual(response.status_int, 413)
        self.assertSearchIndexSize(0)
        response = self.app.post_json(self.url, dict([
            (str(i), str(i)) for i in xrange(0, main._SAFETY_LIMIT + 1)]),
                                      status=413)
        self.assertEqual(response.status_int, 413)
        self.assertSearchIndexSize(0)
        response = self.app.put_json(self.url, dict([
            (str(i), str(i)) for i in xrange(0, main._SAFETY_LIMIT + 1)]),
                                      status=413)
        self.assertEqual(response.status_int, 413)
        self.assertSearchIndexSize(0)

    def test_search(self):
        """Test searching documents in the search index."""
        response = self.app.put_json(self.url, DATA)
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(len(DATA))

        response = self.app.get(self.url)
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(len(DATA))
        self.assertEqual(response.json, [])
        for value, expected in [
            ('Robotic', ['Doraemon']),
            ('robotic', ['Doraemon']),
            ('Future', ['Doraemon']),
            ('future', ['Doraemon']),
            ('CAT', ['Doraemon', 'Heathcliff']),
            ('Cat', ['Doraemon', 'Heathcliff']),
            ('cat', ['Doraemon', 'Heathcliff']),
            ('Loves lasagna', ['Garfield']),
            ('Hates Mondays.', ['Garfield']),
            ('Fancy', ['Top_Cat']),
            ('fancy', ['Top_Cat'])]:
            response = self.app.get(self.url, params={'q': value})
            self.assertEqual(response.status_int, 200)
            self.assertSearchIndexSize(len(DATA))
            self.assertEqual(response.json, expected)
        response = self.app.delete_json(self.url, ['Doraemon'])
        self.assertEqual(response.status_int, 200)
        self.assertSearchIndexSize(len(DATA) - 1)
        for value, expected in [
            ('Robotic', []),
            ('robotic', []),
            ('Future', []),
            ('future', []),
            ('CAT', ['Heathcliff']),
            ('Cat', ['Heathcliff']),
            ('cat', ['Heathcliff']),
            ('Loves lasagna', ['Garfield']),
            ('Hates Mondays.', ['Garfield']),
            ('Fancy', ['Top_Cat']),
            ('fancy', ['Top_Cat'])]:
            response = self.app.get(self.url, params={'q': value})
            self.assertEqual(response.status_int, 200)
            self.assertSearchIndexSize(len(DATA) - 1)
            self.assertEqual(response.json, expected)
