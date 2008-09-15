import bisect
import heapq
from itertools import islice

import BTrees
from persistent.mapping import PersistentMapping
from persistent import Persistent
import transaction

from zope.interface import implements
from zope.interface import Interface
from zope.interface import Attribute

from zope.index.interfaces import IInjection
from zope.index.interfaces import IIndexSearch

from zope.index.text import TextIndex
from zope.index.field import FieldIndex
from zope.index.keyword import KeywordIndex

_marker = ()

class ICatalog(IIndexSearch, IInjection):
    def searchResults(**query):
        """Search on the given indexes."""

    def updateIndexes(items):
        """Reindex all objects in the items sequence [(docid, obj),..] in all
        indexes."""

    def updateIndex(name, items):
        """Reindex all objects in the items sequence [(docid, obj),..] in
        the named index."""

class ICatalogIndex(IIndexSearch, IInjection):
    """ An index that adapts objects to an attribute or callable value
    on an object """
    interface = Attribute('The interface that object to be indexed will '
                          'be adapted against to provide its catalog value')

class ICatalogAdapter(Interface):
    def __call__(default):
        """ Return the value or the default if the object no longer
        has any value for the adaptation"""

_marker = ()

class CatalogIndex(object):
    """ Abstract class for interface-based lookup """

    def __init__(self, discriminator, *args, **kwargs):
        super(CatalogIndex, self).__init__(*args, **kwargs)
        if not callable(discriminator):
            if not isinstance(discriminator, basestring):
                raise ValueError('discriminator value must be callable or a '
                                 'string')
        self.discriminator = discriminator

    def index_doc(self, docid, object):
        if callable(self.discriminator):
            value = self.discriminator(object, _marker)
        else:
            value = getattr(object, self.discriminator, _marker)

        if value is _marker:
            # unindex the previous value
            super(CatalogIndex, self).unindex_doc(docid)
            return None

        if isinstance(value, Persistent):
            raise ValueError('Catalog cannot index persistent object %s' %
                             value)

        return super(CatalogIndex, self).index_doc(docid, value)

class CatalogTextIndex(CatalogIndex, TextIndex):
    implements(ICatalogIndex)

class CatalogFieldIndex(CatalogIndex, FieldIndex):
    implements(ICatalogIndex)
    use_lazy = False # for unit testing
    use_nbest = False # for unit testing

    def sort(self, docids, reverse=False, limit=None):
        if limit is not None:
            limit = int(limit)
            if limit < 1:
                raise ValueError('limit must be 1 or greater')

        if not docids:
            raise StopIteration
            
        numdocs = self._num_docs.value
        if not numdocs:
            raise StopIteration

        rev_index = self._rev_index
        fwd_index = self._fwd_index

        rlen = len(docids)

        # use_lazy and use_nbest computations lifted wholesale from
        # Zope2 catalog without questioning reasoning
        use_lazy = (rlen > (numdocs * (rlen / 100 + 1)))
        use_nbest = limit and limit * 4 < rlen

        # overrides for unit tests
        if self.use_lazy:
            use_lazy = True
        if self.use_nbest:
            use_nbest = True

        marker = _marker

        if use_nbest:
            # this is a sort with a limit that appears useful, try to
            # take advantage of the fact that we can keep a smaller
            # set of simultaneous values in memory; use generators
            # and heapq functions to do so.
            def nsort():
                for docid in docids:
                    val = rev_index.get(docid, marker)
                    if val is not marker:
                        yield (val, docid)
            iterable = nsort()
            if reverse:
                # we use a generator as an iterable in the reverse
                # sort case because the nlargest implementation does
                # not manifest the whole thing into memory at once if
                # we do so.
                for val in heapq.nlargest(limit, iterable):
                    yield val[1]

            else:
                # lifted from heapq.nsmallest
                it = iter(iterable)
                result = sorted(islice(it, 0, limit))
                if not result:
                    yield StopIteration
                insort = bisect.insort
                pop = result.pop
                los = result[-1]    # los --> Largest of the nsmallest
                for elem in it:
                    if los <= elem:
                        continue
                    insort(result, elem)
                    pop()
                    los = result[-1]
                for val in result:
                    yield val[1]

        else:
            if use_lazy and not reverse:
                # Since this the sort is not reversed, and the number
                # of results in the search result set is much larger
                # than the number of items in this index, we assume it
                # will be fastest to iterate over all of our forward
                # BTree's items instead of using a full sort, as our
                # forward index is already sorted in ascending order
                # by value. The Zope 2 catalog implementation claims
                # that this case is rarely exercised in practice.
                n = 0
                for stored_docids in fwd_index.values():
                    isect = self.family.IF.intersection(docids, stored_docids)
                    for docid in isect:
                        if limit and n >= limit:
                            raise StopIteration
                        n += 1
                        yield docid
            else:
                # If the result set is not much larger than the number
                # of documents in this index, or if we need to sort in
                # reverse order, use a non-lazy sort.
                n = 0
                for docid in sorted(docids, key=rev_index.get, reverse=reverse):
                    if rev_index.get(docid, marker) is not marker:
                        # we skip docids that are not in this index (as
                        # per Z2 catalog implementation)
                        if limit and n >= limit:
                            raise StopIteration
                        n += 1
                        yield docid

    def unindex_doc(self, docid):
        """See interface IInjection; base class overridden to be able
        to index None values """
        rev_index = self._rev_index
        value = rev_index.get(docid, _marker)
        if value is _marker:
            return # not in index

        del rev_index[docid]

        try:
            set = self._fwd_index[value]
            set.remove(docid)
        except KeyError:
            # This is fishy, but we don't want to raise an error.
            # We should probably log something.
            # but keep it from throwing a dirty exception
            set = 1

        if not set:
            del self._fwd_index[value]

        self._num_docs.change(-1)

                
class CatalogKeywordIndex(CatalogIndex, KeywordIndex):
    normalize = False
    implements(ICatalogIndex)

    def apply(self, query):
        operator = 'and'
        if isinstance(query, dict):
            if 'operator' in query:
                operator = query.pop('operator')
            query = query['query']
        return self.search(query, operator=operator)

    def _insert_forward(self, docid, words):
        """insert a sequence of words into the forward index """

        idx = self._fwd_index
        has_key = idx.has_key
        for word in words:
            if not has_key(word):
                idx[word] = self.family.IF.Set()
            idx[word].insert(docid)

    def search(self, query, operator='and'):
        """Execute a search given by 'query'."""
        if isinstance(query, basestring):
            query = [query]

        f = {'and' : self.family.IF.intersection,
             'or' : self.family.IF.union,
             }[operator]
    
        rs = None
        for word in query:
            docids = self._fwd_index.get(word, self.family.IF.Set())
            rs = f(rs, docids)
            
        if rs:
            return rs
        else:
            return self.family.IF.Set()

class Catalog(PersistentMapping):

    implements(ICatalog)

    family = BTrees.family32

    def __init__(self, family=None):
        PersistentMapping.__init__(self)
        if family is not None:
            self.family = family

    def clear(self):
        for index in self.values():
            index.clear()

    def index_doc(self, docid, obj):
        """Register the data in indexes of this catalog."""
        assertint(docid)
        for index in self.values():
            index.index_doc(docid, obj)

    def unindex_doc(self, docid):
        """Unregister the data from indexes of this catalog."""
        assertint(docid)
        for index in self.values():
            index.unindex_doc(docid)

    def __setitem__(self, name, index):
        if not ICatalogIndex.providedBy(index):
            raise ValueError('%s does not provide ICatalogIndex')
        index.__parent__ = self
        index.__name__ = name
        return PersistentMapping.__setitem__(self, name, index)
            
    def updateIndex(self, name, items):
        index = self[name]
        for docid, obj in items:
            assertint(docid)
            index.index_doc(docid, obj)

    def updateIndexes(self, items):
        for docid, obj in items:
            assertint(docid)
            for index in self.values():
                index.index_doc(docid, obj)

    def searchResults(self, **query):
        sort_index = None
        reverse = False
        limit = None
        if 'sort_index' in query:
            sort_index = query.pop('sort_index')
        if 'reverse' in query:
            reverse = query.pop('reverse')
        if 'limit' in query:
            limit = query.pop('limit')

        results = []
        for index_name, index_query in query.items():
            index = self.get(index_name)
            if index is None:
                raise ValueError('No such index %s' % index_name)
            r = index.apply(index_query)
            if r is None:
                continue
            if not r:
                # empty results
                return 0, r
            results.append((len(r), r))

        if not results:
            # no applicable indexes, so catalog was not applicable
            return 0, ()

        results.sort() # order from smallest to largest

        _, result = results.pop(0)
        for _, r in results:
            _, result = self.family.IF.weightedIntersection(result, r)

        numdocs = len(result)

        if sort_index:
            index = self[sort_index]
            result = index.sort(result, reverse=reverse, limit=limit)

        if limit is None:
            return numdocs, result
        else:
            return min(numdocs, limit), result

    def apply(self, query):
        return self.searchResults(**query)

def assertint(docid):
    if not isinstance(docid, int):
        raise ValueError('%r is not an integer value; document ids must be '
                         'integers' % docid)

class CatalogFactory(object):
    def __call__(self, connection_handler=None):
        conn = self.db.open()
        if connection_handler:
            connection_handler(conn)
        root = conn.root()
        if root.get(self.appname) is None:
            root[self.appname] = Catalog()
        return root[self.appname]

class FileStorageCatalogFactory(CatalogFactory):
    def __init__(self, filename, appname):
        from ZODB.FileStorage.FileStorage import FileStorage
        from ZODB.DB import DB
        f = FileStorage(filename)
        self.db = DB(f)
        self.appname = appname

    def __del__(self):
        self.db.close()
        
class ConnectionManager(object):
    def __call__(self, conn):
        self.conn = conn

    def close(self):
        self.conn.close()

    def __del__(self):
        self.close()

    def commit(self, transaction=transaction):
        transaction.commit()

