#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2014 Zuza Software Foundation
# Copyright 2013-2014 Evernote Corporation
#
# This file is part of Pootle.
#
# Pootle is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# translate is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with translate; if not, write to the Free Software
# Foundation, Inc., 59

__all__ = ('TreeItem', 'CachedMethods',)

import os
import psutil

from datetime import datetime
from functools import wraps

from translate.filters.decorators import Category

from django.core.cache import cache
from django.utils.encoding import iri_to_uri

from pootle_app import hpy_obj
from pootle.core.log import log
from pootle_misc.util import (getfromcache, dictsum, get_cached_value,
                              set_cached_value, datetime_min)
from pootle_misc.checks import get_qualitychecks_by_category


def bytes_to_mb(bytes):
    return bytes * 1.0 / 1048576

def statslog(function):
    @wraps(function)
    def _statslog(instance, *args, **kwargs):
        log_stat = kwargs.pop('log_stat', False)

        if log_stat:
            start = datetime.now()
            params = {
                'name': function.__name__,
                'key': instance.get_cachekey(),
            }
            if hpy_obj is not None:
                heap_size = hpy_obj.heap().size
                heapu_size = hpy_obj.heapu().size
                rss = psutil.Process(os.getpid()).memory_info().rss
                params.update({
                    'heap': bytes_to_mb(heap_size),
                    'heapu': bytes_to_mb(heapu_size),
                    'rss': bytes_to_mb(rss),
                })

                log('before %(name)s for %(key)s\t'
                    'heap=%(heap)0.2fMb\t'
                    'heapu=%(heapu)0.2fMb\t'
                    'rss=%(rss)0.2fMb\t'
                     % params)

        result = function(instance, *args, **kwargs)

        if log_stat:
            end = datetime.now()
            params.update({'time': end - start,})
            if hpy_obj is not None:
                new_heap_size = hpy_obj.heap().size
                new_heapu_size = hpy_obj.heapu().size
                new_rss = psutil.Process(os.getpid()).memory_info().rss
                params.update({
                    'heap': bytes_to_mb(new_heap_size),
                    'heap_delta': bytes_to_mb(new_heap_size - heap_size),
                    'heapu': bytes_to_mb(new_heapu_size),
                    'heapu_delta': bytes_to_mb(new_heapu_size - heapu_size),
                    'rss': bytes_to_mb(new_rss),
                    'rss_delta': bytes_to_mb(new_rss - rss),
                })

                log('after %(name)s for %(key)s\t'
                    'heap=%(heap)0.2fMb(%(heap_delta)+0.2fMb)\t'
                    'heapu=%(heapu)0.2fMb(%(heapu_delta)+0.2fMb)\t'
                    'rss=%(rss)0.2fMb(%(rss_delta)+0.2fMb)\t'
                    'time=%(time)s'
                    % params)
            else:
                log("%(name)s for %(key)s\ttime=%(time)s" % params)

        return result
    return _statslog


class CachedMethods(object):
    """Cached method names."""
    CHECKS = 'get_checks'
    TOTAL = 'get_total_wordcount'
    TRANSLATED = 'get_translated_wordcount'
    FUZZY = 'get_fuzzy_wordcount'
    LAST_ACTION = 'get_last_action'
    SUGGESTIONS = 'get_suggestion_count'
    MTIME = 'get_mtime'
    LAST_UPDATED = 'get_last_updated'

    # Check refresh_stats command when add a new CachedMethod

    @classmethod
    def get_all(self):
        return [getattr(self, x) for x in
                filter(lambda x: x[:2] != '__' and x != 'get_all', dir(self))]


class TreeItem(object):
    def __init__(self, *args, **kwargs):
        self.children = None
        self.initialized = False
        self._flagged_for_deletion = set()
        super(TreeItem, self).__init__()

    def get_children(self):
        """This method will be overridden in descendants"""
        return []

    def get_parents(self):
        """This method will be overridden in descendants"""
        return []

    def get_cachekey(self):
        """This method will be overridden in descendants"""
        raise NotImplementedError('`get_cachekey()` not implemented')

    def _get_total_wordcount(self):
        """This method will be overridden in descendants"""
        return 0

    def _get_translated_wordcount(self):
        """This method will be overridden in descendants"""
        return 0

    def _get_fuzzy_wordcount(self):
        """This method will be overridden in descendants"""
        return 0

    def _get_suggestion_count(self):
        """This method will be overridden in descendants"""
        return 0

    def _get_checks(self):
        """This method will be overridden in descendants"""
        return {'unit_count': 0, 'checks': {}}

    def _get_last_action(self):
        """This method will be overridden in descendants"""
        return {'id': 0, 'mtime': 0, 'snippet': ''}

    def _get_mtime(self):
        """This method will be overridden in descendants"""
        return datetime_min

    def _get_last_updated(self):
        """This method will be overridden in descendants"""
        return {'id': 0, 'creation_time': 0, 'snippet': ''}

    def initialize_children(self):
        if not self.initialized:
            self.children = self.get_children()
            self.initialized = True

    @getfromcache
    @statslog
    def get_total_wordcount(self):
        """calculate total wordcount statistics"""
        self.initialize_children()
        return (self._get_total_wordcount() +
                self._sum('get_total_wordcount'))

    @getfromcache
    @statslog
    def get_translated_wordcount(self):
        """calculate translated units statistics"""
        self.initialize_children()
        return (self._get_translated_wordcount() +
                self._sum('get_translated_wordcount'))

    @getfromcache
    @statslog
    def get_fuzzy_wordcount(self):
        """calculate untranslated units statistics"""
        self.initialize_children()
        return (self._get_fuzzy_wordcount() +
                self._sum('get_fuzzy_wordcount'))

    @getfromcache
    @statslog
    def get_suggestion_count(self):
        """check if any child store has suggestions"""
        self.initialize_children()
        return (self._get_suggestion_count() +
                self._sum('get_suggestion_count'))

    @getfromcache
    @statslog
    def get_last_action(self):
        """get last action HTML snippet"""
        self.initialize_children()

        return max(
            [self._get_last_action()] +
            [item.get_last_action() for item in self.children],
            key=lambda x: x['mtime'] if 'mtime' in x else 0
        )

    @getfromcache
    @statslog
    def get_mtime(self):
        """get latest modification time"""
        self.initialize_children()
        return max(
            [self._get_mtime()] +
            [item.get_mtime() for item in self.children]
        )

    @getfromcache
    @statslog
    def get_last_updated(self):
        """get last updated"""
        self.initialize_children()
        return max(
            [self._get_last_updated()] +
            [item.get_last_updated() for item in self.children],
            key=lambda x: x['creation_time'] if 'creation_time' in x else 0
        )

    def _sum(self, name):
        return sum([
            getattr(item, name)() for item in self.children
        ])

    def get_stats(self, include_children=True):
        """get stats for self and - optionally - for children"""
        self.initialize_children()

        result = {
            'total': self.get_total_wordcount(log_stat=True),
            'translated': self.get_translated_wordcount(log_stat=True),
            'fuzzy': self.get_fuzzy_wordcount(log_stat=True),
            'suggestions': self.get_suggestion_count(log_stat=True),
            'lastaction': self.get_last_action(log_stat=True),
            'critical': self.get_error_unit_count(log_stat=True),
            'lastupdated': self.get_last_updated(log_stat=True)
        }

        if include_children:
            result['children'] = {}
            for item in self.children:
                code = (self._get_code(item) if hasattr(self, '_get_code')
                                             else item.code)
                result['children'][code] = item.get_stats(False)

        return result

    def refresh_stats(self, include_children=True):
        """refresh stats for self and for children"""
        self.initialize_children()

        if include_children:
            for item in self.children:
                item.refresh_stats()
            else:
                self.clear_all_cache(parents=True, children=False)

        self.get_total_wordcount()
        self.get_translated_wordcount()
        self.get_fuzzy_wordcount()
        self.get_suggestion_count()
        self.get_last_action()
        self.get_checks()
        self.get_mtime()
        self.get_last_updated()

    @getfromcache
    @statslog
    def get_checks(self):
        result = self._get_checks()
        self.initialize_children()
        for item in self.children:
            item_res = item.get_checks()
            result['checks'] = dictsum(result['checks'], item_res['checks'])
            result['unit_count'] += item_res['unit_count']

        return result

    def get_error_unit_count(self, log_stat=False):
        check_stats = self.get_checks(log_stat=log_stat)

        return check_stats['unit_count']

    def get_critical_url(self):
        critical = ','.join(get_qualitychecks_by_category(Category.CRITICAL))
        return self.get_translate_url(check=critical)

    def flag_for_deletion(self, *args):
        for key in args:
            self._flagged_for_deletion.add(key)

    def set_last_action(self, last_action):
        set_cached_value(self, 'get_last_action', last_action)
        parents = self.get_parents()
        for p in parents:
            pla = get_cached_value(p, 'get_last_action')
            if pla and pla['mtime'] < last_action['mtime']:
                p.set_last_action(last_action)

    def _clear_cache(self, keys, parents=True, children=False):
        itemkey = self.get_cachekey()
        for key in keys:
            cachekey = iri_to_uri(itemkey + ":" + key)
            cache.delete(cachekey)
        if keys:
            log("%s deleted from %s cache" % (keys, itemkey))

        if parents:
            parents = self.get_parents()
            for p in parents:
                p._clear_cache(keys, parents=parents, children=False)

        if children:
            self.initialize_children()
            for item in self.children:
                item._clear_cache(keys, parents=False, children=True)

    def clear_flagged_cache(self, parents=True, children=False):
        self._clear_cache(self._flagged_for_deletion,
                          parents=parents, children=children)
        self._flagged_for_deletion = set()

    def clear_all_cache(self, children=True, parents=True):
        all_cache_methods = CachedMethods.get_all()
        self.flag_for_deletion(*all_cache_methods)
        self.clear_flagged_cache(children=children, parents=parents)
