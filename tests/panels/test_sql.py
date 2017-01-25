# coding: utf-8

from __future__ import absolute_import, unicode_literals

import unittest

from django.contrib.auth.models import User
from django.db import connection
from django.db.utils import DatabaseError
from django.shortcuts import render
from django.test.utils import override_settings

from ..base import BaseTestCase


class SQLPanelTestCase(BaseTestCase):

    def setUp(self):
        super(SQLPanelTestCase, self).setUp()
        self.panel = self.toolbar.get_panel_by_id('SQLPanel')
        self.panel.enable_instrumentation()

    def tearDown(self):
        self.panel.disable_instrumentation()
        super(SQLPanelTestCase, self).tearDown()

    def test_disabled(self):
        config = {
            'DISABLE_PANELS': set(['debug_toolbar.panels.sql.SQLPanel'])
        }
        self.assertTrue(self.panel.enabled)
        with self.settings(DEBUG_TOOLBAR_CONFIG=config):
            self.assertFalse(self.panel.enabled)

    def test_recording(self):
        self.assertEqual(len(self.panel._queries), 0)

        list(User.objects.all())

        # ensure query was logged
        self.assertEqual(len(self.panel._queries), 1)
        query = self.panel._queries[0]
        self.assertEqual(query[0], 'default')
        self.assertTrue('sql' in query[1])
        self.assertTrue('duration' in query[1])
        self.assertTrue('stacktrace' in query[1])

        # ensure the stacktrace is populated
        self.assertTrue(len(query[1]['stacktrace']) > 0)

    def test_non_ascii_query(self):
        self.assertEqual(len(self.panel._queries), 0)

        # non-ASCII text query
        list(User.objects.extra(where=["username = 'apéro'"]))
        self.assertEqual(len(self.panel._queries), 1)

        # non-ASCII text parameters
        list(User.objects.filter(username='thé'))
        self.assertEqual(len(self.panel._queries), 2)

        # non-ASCII bytes parameters
        list(User.objects.filter(username='café'.encode('utf-8')))
        self.assertEqual(len(self.panel._queries), 3)

        self.panel.process_response(self.request, self.response)
        self.panel.generate_stats(self.request, self.response)

        # ensure the panel renders correctly
        self.assertIn('café', self.panel.content)

    def test_long_singleword_query(self):
        """
        #Test related to Issue #909
        https://github.com/jazzband/django-debug-toolbar/issues/909

        If django-debug-toolbar is used
        with a module such as django-picklefield
        (https://github.com/gintas/django-picklefield)
        it will be very easy to generate a INSERT/UPDATE query
        containing a very long word (base64 encoded data structure).

        When django-debug-toolbar tries to represent it
        a MemoryError can be caused by the sqlparse's REGEX
        https://github.com/andialbrecht/sqlparse/blob/0.2.2/sqlparse/lexer.py#L59

        So when this happen we just want to stop the repsentation of this word.

        In order to make a test that will fails on every machine, a temporal
        Memory Limit will be set during the test.
        """

        short_word = 'y' * 10
        very_long_word = 'x' * (1024 * 1024) #1MB

        #now set memory_limits
        import psutil
        process = psutil.Process()
        memory_resource = psutil.RLIMIT_AS
        memory_usage = process.memory_info().vms
        current_memory_limit = process.rlimit(memory_resource)
        current_soft, current_hard = current_memory_limit

        leave_free_memory = 100 * 1024 * 1024 #100MB
        max_memory_limit = memory_usage+leave_free_memory

        #set soft memory limit
        process.rlimit(memory_resource, (max_memory_limit, current_hard))

        self.assertEqual(len(self.panel._queries), 0)

        list(User.objects.filter(username=short_word))
        self.assertEqual(len(self.panel._queries), 1)

        list(User.objects.filter(username=very_long_word))
        self.assertEqual(len(self.panel._queries), 2)

        self.panel.process_response(self.request, self.response)
        self.panel.generate_stats(self.request, self.response)

        #restore the original memory limits
        process.rlimit(memory_resource, (current_soft, current_hard))

        # ensure the panel renders correctly
        from debug_toolbar.panels.sql.utils import UNREPRESENTABLE_STRING
        self.assertTrue(short_word in self.panel.content)
        self.assertTrue(UNREPRESENTABLE_STRING in self.panel.content)

    def test_insert_content(self):
        """
        Test that the panel only inserts content after generate_stats and
        not the process_response.
        """
        list(User.objects.filter(username='café'.encode('utf-8')))
        self.panel.process_response(self.request, self.response)
        # ensure the panel does not have content yet.
        self.assertNotIn('café', self.panel.content)
        self.panel.generate_stats(self.request, self.response)
        # ensure the panel renders correctly.
        self.assertIn('café', self.panel.content)

    @unittest.skipUnless(connection.vendor == 'postgresql',
                         'Test valid only on PostgreSQL')
    def test_erroneous_query(self):
        """
        Test that an error in the query isn't swallowed by the middleware.
        """
        try:
            connection.cursor().execute("erroneous query")
        except DatabaseError as e:
            self.assertTrue('erroneous query' in str(e))

    def test_disable_stacktraces(self):
        self.assertEqual(len(self.panel._queries), 0)

        with self.settings(DEBUG_TOOLBAR_CONFIG={'ENABLE_STACKTRACES': False}):
            list(User.objects.all())

        # ensure query was logged
        self.assertEqual(len(self.panel._queries), 1)
        query = self.panel._queries[0]
        self.assertEqual(query[0], 'default')
        self.assertTrue('sql' in query[1])
        self.assertTrue('duration' in query[1])
        self.assertTrue('stacktrace' in query[1])

        # ensure the stacktrace is empty
        self.assertEqual([], query[1]['stacktrace'])

    @override_settings(DEBUG=True, TEMPLATES=[{
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'OPTIONS': {'debug': True, 'loaders': ['tests.loaders.LoaderWithSQL']},
    }])
    def test_regression_infinite_recursion(self):
        """
        Test case for when the template loader runs a SQL query that causes
        an infinite recursion in the SQL panel.
        """
        self.assertEqual(len(self.panel._queries), 0)

        render(self.request, "basic.html", {})

        # Two queries are logged because the loader runs SQL every time a
        # template is loaded and basic.html extends base.html.
        self.assertEqual(len(self.panel._queries), 2)
        query = self.panel._queries[0]
        self.assertEqual(query[0], 'default')
        self.assertTrue('sql' in query[1])
        self.assertTrue('duration' in query[1])
        self.assertTrue('stacktrace' in query[1])

        # ensure the stacktrace is populated
        self.assertTrue(len(query[1]['stacktrace']) > 0)
